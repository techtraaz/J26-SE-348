"""Full LangGraph hybrid parallel-sequential.
- No join node: edge list waits for both branches.
- Explicit early_stop flag in state (never inferred from trace shape).
- DQ-rejected docs excluded from Compliance + Anomaly; stop when ALL rejected.
- Nodes read case from state; KG + per-run seq counter travel via config
  (LangGraph injects run config ONLY into a parameter named `config`).
- Trace carries per-run completion-order seq numbers 1..5 (finish order,
  not start order). Counter is created fresh per run: concurrent runs safe.
- run_case uses final_findings directly, no or-fallback. Early stop returns
  the DQ findings as reasons with status not_auditable (never a clean look).
- Stream sends JSON-safe model_dump data + final result event, single run.
"""
import itertools
import operator
import time
from typing import Annotated, TypedDict

from langchain_core.runnables import RunnableConfig

from app import config as settings
from app.schemas.case import AuditCase
from app.schemas.findings import AuditResult, TraceEntry
from app.services.agents import (
    anomaly,
    compliance,
    data_quality,
    evidence_validation,
    reasoning,
)
from app.services.kg_client import KGClient, default_kg

VERSION_STORE: dict[str, int] = {}


class OrchestratorConfigError(RuntimeError):
    """A graph node ran without the per-run config it needs (kg + seq)."""


class AuditState(TypedDict):
    case: dict
    findings: Annotated[list, operator.add]
    trace: Annotated[list, operator.add]
    rejected_records: Annotated[list, operator.add]
    reasoned: list
    final_findings: list
    rejected_citations: Annotated[list, operator.add]
    rejected_findings: list
    early_stop: bool


def _case_from(state: AuditState) -> AuditCase:
    return AuditCase.model_validate(state["case"])


def _filtered_case(case: AuditCase, rejected: list[str]) -> AuditCase:
    bad = set(rejected)
    return AuditCase(case_id=case.case_id,
                     docs=[d for d in case.docs if d.doc_id not in bad])


def _kg_from(run_config: RunnableConfig | None) -> KGClient:
    if run_config and isinstance(run_config.get("configurable"), dict):
        kg = run_config["configurable"].get("kg")
        if isinstance(kg, KGClient):
            return kg
    return default_kg()


def _kg_notice(kg: KGClient) -> TraceEntry:
    """One trace line telling the auditor where the KG data came from."""
    return TraceEntry(agent_name="kg", decision_type="source",
                      detail=f"Knowledge graph source: {kg.source}.", seq=0)


def _seq_from(run_config: dict | None) -> itertools.count:
    """Per-run counter. Missing config is a clear error, not a bare KeyError."""
    if not isinstance(run_config, dict):
        raise OrchestratorConfigError(
            "Graph node ran without a run config; 'seq' is required.")
    configurable = run_config.get("configurable")
    if not isinstance(configurable, dict) or "seq" not in configurable:
        raise OrchestratorConfigError(
            "Run config is missing 'configurable.seq'; nodes must run through "
            "the graph.")
    return configurable["seq"]


def build_graph() -> object:
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(AuditState)

    def n_dq(state: AuditState, config: RunnableConfig) -> dict:
        case = _case_from(state)
        f, rejected, t = data_quality.run(case)
        if config is not None:
            for x in t:
                x.seq = next(_seq_from(config))
        return {"findings": f, "trace": t, "rejected_records": rejected,
                "early_stop": len(case.docs) == 0 or
                              (len(rejected) >= len(case.docs) > 0)}

    def route_after_dq(state: AuditState):
        if state.get("early_stop"):
            return END
        return ["compliance", "anomaly"]

    def n_comp(state: AuditState, config: RunnableConfig) -> dict:
        case = _filtered_case(_case_from(state), state.get("rejected_records", []))
        f, t = compliance.run(case, _kg_from(config))
        for x in t:
            x.seq = next(_seq_from(config))
        return {"findings": f, "trace": t}

    def n_anom(state: AuditState, config: RunnableConfig) -> dict:
        case = _filtered_case(_case_from(state), state.get("rejected_records", []))
        f, t = anomaly.run(case)
        for x in t:
            x.seq = next(_seq_from(config))
        return {"findings": f, "trace": t}

    def n_reas(state: AuditState, config: RunnableConfig) -> dict:
        case = _case_from(state)
        merged, t = reasoning.run(case, list(state.get("findings", [])),
                                  _kg_from(config))
        for x in t:
            x.seq = next(_seq_from(config))
        return {"reasoned": merged, "trace": t}

    def n_val(state: AuditState, config: RunnableConfig) -> dict:
        case = _case_from(state)
        base = list(state["reasoned"])  # direct key, no or-fallback
        kept, rejected, bad_ids, t = evidence_validation.run(case, base)
        for x in t:
            x.seq = next(_seq_from(config))
        return {"final_findings": kept, "rejected_findings": rejected,
                "rejected_citations": bad_ids, "trace": t}

    g.add_node("data_quality", n_dq)
    g.add_node("compliance", n_comp)
    g.add_node("anomaly", n_anom)
    g.add_node("reasoning", n_reas)
    g.add_node("evidence_validation", n_val)

    g.add_edge(START, "data_quality")
    g.add_conditional_edges("data_quality", route_after_dq)
    g.add_edge(["compliance", "anomaly"], "reasoning")
    g.add_edge("reasoning", "evidence_validation")
    g.add_edge("evidence_validation", END)
    return g.compile()


GRAPH = build_graph()  # built once; case + kg + seq travel via state / config


def _initial(case: AuditCase) -> dict:
    return {"case": case.model_dump(), "findings": [], "trace": [],
            "rejected_records": [], "reasoned": [], "final_findings": [],
            "rejected_citations": [], "rejected_findings": [], "early_stop": False}


def _fresh_cfg(kg: KGClient | None) -> dict:
    return {"configurable": {"kg": kg or default_kg(), "seq": itertools.count(1)}}


def run_case(case: AuditCase, kg: KGClient | None = None) -> AuditResult:
    kg = kg or default_kg()
    start = time.perf_counter()
    out = GRAPH.invoke(_initial(case), config=_fresh_cfg(kg))
    latency_ms = round((time.perf_counter() - start) * 1000, 3)
    v = VERSION_STORE.get(case.case_id, 0) + 1
    VERSION_STORE[case.case_id] = v
    trace = list(out.get("trace", [])) + [_kg_notice(kg)]
    if out.get("early_stop"):
        # not_auditable: DQ reasons included, never looks like a clean case
        return AuditResult(case_id=case.case_id, version=v, status="not_auditable",
                           findings=list(out.get("findings", [])),
                           trace=trace,
                           rejected_records=list(out.get("rejected_records", [])),
                           rejected_citations=[], rejected_findings=[],
                           kg_source=kg.source, latency_ms=latency_ms)
    return AuditResult(case_id=case.case_id, version=v,
                       status=settings.FINDINGS_STATUS_DEFAULT,
                       findings=list(out.get("final_findings", [])),
                       trace=trace,
                       rejected_records=list(out.get("rejected_records", [])),
                       rejected_citations=list(out.get("rejected_citations", [])),
                       rejected_findings=list(out.get("rejected_findings", [])),
                       kg_source=kg.source, latency_ms=latency_ms)


def stream_case(case: AuditCase, kg: KGClient | None = None):
    """Single graph run. Yields JSON-safe per-node updates, then one final result.
    Version bumped exactly once."""
    kg = kg or default_kg()
    start = time.perf_counter()
    acc: dict = {"trace": [], "rejected_records": [], "rejected_citations": [],
                 "reasoned": [], "final_findings": [], "rejected_findings": [],
                 "findings": [], "early_stop": False}
    for chunk in GRAPH.stream(_initial(case), config=_fresh_cfg(kg), stream_mode="updates"):
        safe: dict = {}
        for node, data in chunk.items():
            node_data: dict = {}
            if isinstance(data, dict):
                for k, val in data.items():
                    items = val if isinstance(val, list) else [val]
                    dumps = [x.model_dump() if hasattr(x, "model_dump") else x for x in items]
                    node_data[k] = dumps if isinstance(val, list) else (dumps[0] if dumps else None)
                    if k in acc and isinstance(val, list):
                        if k in ("reasoned", "final_findings", "rejected_findings"):
                            acc[k] = list(val)
                        elif k == "early_stop":
                            pass
                        else:
                            acc[k].extend(val)
                    elif k == "early_stop":
                        acc[k] = bool(val)
            safe[node] = node_data
        yield {"event": "update", "data": safe}
    latency_ms = round((time.perf_counter() - start) * 1000, 3)
    v = VERSION_STORE.get(case.case_id, 0) + 1
    VERSION_STORE[case.case_id] = v
    trace = list(acc["trace"]) + [_kg_notice(kg)]
    if acc["early_stop"]:
        res = AuditResult(case_id=case.case_id, version=v, status="not_auditable",
                          findings=acc["findings"], trace=trace,
                          rejected_records=acc["rejected_records"],
                          rejected_citations=[], rejected_findings=[],
                          kg_source=kg.source, latency_ms=latency_ms)
    else:
        res = AuditResult(case_id=case.case_id, version=v,
                          status=settings.FINDINGS_STATUS_DEFAULT,
                          findings=acc["final_findings"], trace=trace,
                          rejected_records=acc["rejected_records"],
                          rejected_citations=acc["rejected_citations"],
                          rejected_findings=acc["rejected_findings"],
                          kg_source=kg.source, latency_ms=latency_ms)
    yield {"event": "result", "data": res.model_dump()}
