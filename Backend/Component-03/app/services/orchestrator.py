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
from app.services.events import EventPublisher, default_publisher
from app.services.kg_client import KGClient, default_kg

VERSION_STORE: dict[str, int] = {}


def _next_version(case_id: str) -> int:
    """Bump and return the version for a case. One bump per run, never zero."""
    v = VERSION_STORE.get(case_id, 0) + 1
    VERSION_STORE[case_id] = v
    return v


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


def _pub_from(run_config: RunnableConfig | None) -> EventPublisher:
    if isinstance(run_config, dict):
        cfg = run_config.get("configurable")
        if isinstance(cfg, dict) and isinstance(cfg.get("publisher"), EventPublisher):
            return cfg["publisher"]
    return default_publisher()


def _emit_agent(config: RunnableConfig | None, case_id: str, agent: str,
                findings: list, trace: list) -> None:
    """One C4 agent_end event per agent; best-effort, never raised."""
    entry = trace[0] if trace else None
    _pub_from(config).agent_end(
        case_id, agent, len(findings),
        entry.model_dump() if entry is not None else {})


def build_graph() -> object:
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(AuditState)

    def n_dq(state: AuditState, config: RunnableConfig) -> dict:
        case = _case_from(state)
        f, rejected, t = data_quality.run(case)
        if config is not None:
            for x in t:
                x.seq = next(_seq_from(config))
        _emit_agent(config, case.case_id, "data_quality", f, t)
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
        _emit_agent(config, case.case_id, "compliance", f, t)
        return {"findings": f, "trace": t}

    def n_anom(state: AuditState, config: RunnableConfig) -> dict:
        case = _filtered_case(_case_from(state), state.get("rejected_records", []))
        f, t = anomaly.run(case)
        for x in t:
            x.seq = next(_seq_from(config))
        _emit_agent(config, case.case_id, "anomaly", f, t)
        return {"findings": f, "trace": t}

    def n_reas(state: AuditState, config: RunnableConfig) -> dict:
        case = _case_from(state)
        merged, t = reasoning.run(case, list(state.get("findings", [])),
                                  _kg_from(config))
        for x in t:
            x.seq = next(_seq_from(config))
        _emit_agent(config, case.case_id, "reasoning", merged, t)
        return {"reasoned": merged, "trace": t}

    def n_val(state: AuditState, config: RunnableConfig) -> dict:
        case = _case_from(state)
        base = list(state["reasoned"])  # direct key, no or-fallback
        kept, rejected, bad_ids, t = evidence_validation.run(case, base)
        for x in t:
            x.seq = next(_seq_from(config))
        _emit_agent(config, case.case_id, "evidence_validation", kept, t)
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


def _fresh_cfg(kg: KGClient | None,
               publisher: EventPublisher | None = None) -> dict:
    return {"configurable": {"kg": kg or default_kg(), "seq": itertools.count(1),
                             "publisher": publisher or default_publisher()}}


def run_case(case: AuditCase, kg: KGClient | None = None,
             publisher: EventPublisher | None = None) -> AuditResult:
    kg = kg or default_kg()
    pub = publisher or default_publisher()
    pub.pipeline_start(case.case_id, len(case.docs))
    start = time.perf_counter()
    out = GRAPH.invoke(_initial(case), config=_fresh_cfg(kg, pub))
    latency_ms = round((time.perf_counter() - start) * 1000, 3)
    v = _next_version(case.case_id)
    if out.get("early_stop"):
        # not_auditable: DQ reasons included, never looks like a clean case
        status = "not_auditable"
        findings = list(out.get("findings", []))
        rejected_citations: list[str] = []
        rejected_findings: list = []
    else:
        status = settings.FINDINGS_STATUS_DEFAULT
        findings = list(out.get("final_findings", []))
        rejected_citations = list(out.get("rejected_citations", []))
        rejected_findings = list(out.get("rejected_findings", []))
    pub.pipeline_end(case.case_id, len(findings))
    trace = list(out.get("trace", [])) + [_kg_notice(kg)]
    note = pub.note()
    if note:
        trace.append(TraceEntry(agent_name="events", decision_type="events",
                                detail=note, seq=0))
    res = AuditResult(case_id=case.case_id, version=v, status=status,
                      findings=findings, trace=trace,
                      rejected_records=list(out.get("rejected_records", [])),
                      rejected_citations=rejected_citations,
                      rejected_findings=rejected_findings,
                      kg_source=kg.source, latency_ms=latency_ms,
                      events_published=pub.published)
    return res


def stream_case(case: AuditCase, kg: KGClient | None = None,
                publisher: EventPublisher | None = None):
    """Single graph run. Yields JSON-safe per-node updates, then one final result.
    Version bumped exactly once."""
    kg = kg or default_kg()
    pub = publisher or default_publisher()
    pub.pipeline_start(case.case_id, len(case.docs))
    start = time.perf_counter()
    acc: dict = {"trace": [], "rejected_records": [], "rejected_citations": [],
                 "reasoned": [], "final_findings": [], "rejected_findings": [],
                 "findings": [], "early_stop": False}
    for chunk in GRAPH.stream(_initial(case), config=_fresh_cfg(kg, pub),
                              stream_mode="updates"):
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
    v = _next_version(case.case_id)
    if acc["early_stop"]:
        status = "not_auditable"
        findings = acc["findings"]
        rejected_citations: list = []
        rejected_findings: list = []
    else:
        status = settings.FINDINGS_STATUS_DEFAULT
        findings = acc["final_findings"]
        rejected_citations = acc["rejected_citations"]
        rejected_findings = acc["rejected_findings"]
    pub.pipeline_end(case.case_id, len(findings))
    trace = list(acc["trace"]) + [_kg_notice(kg)]
    note = pub.note()
    if note:
        trace.append(TraceEntry(agent_name="events", decision_type="events",
                                detail=note, seq=0))
    res = AuditResult(case_id=case.case_id, version=v, status=status,
                      findings=findings, trace=trace,
                      rejected_records=acc["rejected_records"],
                      rejected_citations=rejected_citations,
                      rejected_findings=rejected_findings,
                      kg_source=kg.source, latency_ms=latency_ms,
                      events_published=pub.published)
    yield {"event": "result", "data": res.model_dump()}
