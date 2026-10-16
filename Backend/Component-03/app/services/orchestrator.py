"""Full LangGraph hybrid parallel-sequential.
- No join node: edge list waits for both branches.
- Conditional stop when ALL docs rejected (FR2) or empty case -> not_auditable.
- DQ-rejected docs excluded from Compliance + Anomaly.
- Nodes read case from state; graph built once; KG comes via config (injectable).
- Trace carries per-run completion-order seq numbers (finish order, not start order).
- run_case uses final_findings directly, no or-fallback. Early stop returns the
  DQ findings as reasons with status not_auditable (never looks like a clean case).
- Stream sends JSON-safe model_dump data + final result event, single graph run.
"""
import operator
import threading
from typing import Annotated, TypedDict
from app import config
from app.schemas.case import AuditCase
from app.schemas.findings import AuditResult
from app.services.agents import data_quality, compliance, anomaly, reasoning, evidence_validation
from app.services.kg_client import KGClient

VERSION_STORE: dict[str, int] = {}

_SEQ_LOCK = threading.Lock()
_SEQ_VAL = [0]


def _next_seq() -> int:
    with _SEQ_LOCK:
        _SEQ_VAL[0] += 1
        return _SEQ_VAL[0]


class AuditState(TypedDict):
    case: dict
    findings: Annotated[list, operator.add]
    trace: Annotated[list, operator.add]
    rejected_records: Annotated[list, operator.add]
    reasoned: list
    final_findings: list
    rejected_citations: Annotated[list, operator.add]
    rejected_findings: list


def _case_from(state: AuditState) -> AuditCase:
    return AuditCase.model_validate(state["case"])


def _filtered_case(case: AuditCase, rejected: list[str]) -> AuditCase:
    bad = set(rejected)
    return AuditCase(case_id=case.case_id,
                     docs=[d for d in case.docs if d.doc_id not in bad])


def _kg_from(cfg: dict | None) -> KGClient:
    if cfg and isinstance(cfg.get("configurable"), dict):
        kg = cfg["configurable"].get("kg")
        if isinstance(kg, KGClient):
            return kg
    return KGClient()


def build_graph() -> object:
    from langgraph.graph import StateGraph, START, END

    g = StateGraph(AuditState)

    def n_dq(state: AuditState) -> dict:
        case = _case_from(state)
        if len(case.docs) == 0:
            from app.schemas.findings import Finding, TraceEntry
            f = [Finding(finding_id=f"{case.case_id}-CHK006-empty", rule_id="CHK-006",
                         category="format", severity="high",
                         message=f"No documents in case {case.case_id}: nothing could be checked.",
                         evidence_ids=[])]
            t = [TraceEntry(agent_name="data_quality", decision_type="gate",
                            detail="Empty case: nothing to check.", seq=_next_seq())]
            return {"findings": f, "trace": t, "rejected_records": []}
        f, rejected, t = data_quality.run(case)
        for x in t:
            x.seq = _next_seq()
        return {"findings": f, "trace": t, "rejected_records": rejected}

    def route_after_dq(state: AuditState):
        case = _case_from(state)
        if len(case.docs) == 0:
            return END
        # stop when EVERY document failed the DQ gate
        if len(state.get("rejected_records", [])) >= len(case.docs) > 0:
            return END
        return ["compliance", "anomaly"]

    def n_comp(state: AuditState, cfg: dict | None = None) -> dict:
        case = _filtered_case(_case_from(state), state.get("rejected_records", []))
        f, t = compliance.run(case, _kg_from(cfg))
        for x in t:
            x.seq = _next_seq()
        return {"findings": f, "trace": t}

    def n_anom(state: AuditState, cfg: dict | None = None) -> dict:
        case = _filtered_case(_case_from(state), state.get("rejected_records", []))
        f, t = anomaly.run(case)
        for x in t:
            x.seq = _next_seq()
        return {"findings": f, "trace": t}

    def n_reas(state: AuditState) -> dict:
        case = _case_from(state)
        merged, t = reasoning.run(case, list(state.get("findings", [])))
        for x in t:
            x.seq = _next_seq()
        return {"reasoned": merged, "trace": t}

    def n_val(state: AuditState) -> dict:
        case = _case_from(state)
        base = list(state["reasoned"])  # direct key, no or-fallback
        kept, rejected, bad_ids, t = evidence_validation.run(case, base)
        for x in t:
            x.seq = _next_seq()
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


GRAPH = build_graph()  # built once; case + kg travel via state / config


def _initial(case: AuditCase) -> dict:
    return {"case": case.model_dump(), "findings": [], "trace": [],
            "rejected_records": [], "reasoned": [], "final_findings": [],
            "rejected_citations": [], "rejected_findings": []}


def _normalize_seq(trace: list, base: int) -> None:
    for t in trace:
        t.seq -= base


def _is_early_stop(out: dict, case: AuditCase) -> bool:
    names = [t.agent_name for t in out.get("trace", [])]
    return names == ["data_quality"]


def run_case(case: AuditCase, kg: KGClient | None = None) -> AuditResult:
    base = _SEQ_VAL[0]
    out = GRAPH.invoke(_initial(case), config={"configurable": {"kg": kg or KGClient()}})
    trace = list(out.get("trace", []))
    _normalize_seq(trace, base)
    v = VERSION_STORE.get(case.case_id, 0) + 1
    VERSION_STORE[case.case_id] = v
    if _is_early_stop(out, case):
        # not_auditable: DQ reasons included, never looks like a clean case
        return AuditResult(case_id=case.case_id, version=v, status="not_auditable",
                           findings=list(out.get("findings", [])),
                           trace=trace,
                           rejected_records=list(out.get("rejected_records", [])),
                           rejected_citations=[], rejected_findings=[])
    return AuditResult(case_id=case.case_id, version=v,
                       status=config.FINDINGS_STATUS_DEFAULT,
                       findings=list(out.get("final_findings", [])),
                       trace=trace,
                       rejected_records=list(out.get("rejected_records", [])),
                       rejected_citations=list(out.get("rejected_citations", [])),
                       rejected_findings=list(out.get("rejected_findings", [])))


def stream_case(case: AuditCase, kg: KGClient | None = None):
    """Single graph run. Yields JSON-safe per-node updates, then one final result.
    Version bumped exactly once."""
    base = _SEQ_VAL[0]
    acc: dict = {"trace": [], "rejected_records": [], "rejected_citations": [],
                 "reasoned": [], "final_findings": [], "rejected_findings": [],
                 "findings": []}
    for chunk in GRAPH.stream(_initial(case),
                              config={"configurable": {"kg": kg or KGClient()}},
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
                        else:
                            acc[k].extend(val)
            safe[node] = node_data
        yield {"event": "update", "data": safe}
    trace = acc["trace"]
    _normalize_seq(trace, base)
    v = VERSION_STORE.get(case.case_id, 0) + 1
    VERSION_STORE[case.case_id] = v
    early = [getattr(t, "agent_name", "") for t in trace] == ["data_quality"]
    if early:
        res = AuditResult(case_id=case.case_id, version=v, status="not_auditable",
                          findings=acc["findings"], trace=trace,
                          rejected_records=acc["rejected_records"],
                          rejected_citations=[], rejected_findings=[])
    else:
        res = AuditResult(case_id=case.case_id, version=v,
                          status=config.FINDINGS_STATUS_DEFAULT,
                          findings=acc["final_findings"], trace=trace,
                          rejected_records=acc["rejected_records"],
                          rejected_citations=acc["rejected_citations"],
                          rejected_findings=acc["rejected_findings"])
    yield {"event": "result", "data": res.model_dump()}
