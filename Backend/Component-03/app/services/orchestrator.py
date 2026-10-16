"""Full LangGraph hybrid parallel-sequential.
- No join node: edge list waits for both.
- Conditional stop when ALL docs rejected (FR2), not just empty case.
- DQ-rejected docs excluded from Compliance + Anomaly.
- Nodes read case from state; graph built once.
- Trace carries execution seq numbers; never sorted.
- run_case uses final_findings directly, no or-fallback.
- Stream sends JSON-safe model_dump data + final result event.
"""
import itertools
import operator
from typing import Annotated, TypedDict
from app import config
from app.schemas.case import AuditCase
from app.schemas.findings import AuditResult
from app.services.agents import data_quality, compliance, anomaly, reasoning, evidence_validation
from app.services.kg_client import KGClient

VERSION_STORE: dict[str, int] = {}
_SEQ = itertools.count(1)  # execution order stamp, set inside node at run time


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


def _stamp(trace_list: list) -> None:
    for t in trace_list:
        t.seq = next(_SEQ)


def build_graph() -> object:
    from langgraph.graph import StateGraph, START, END

    g = StateGraph(AuditState)

    def n_dq(state: AuditState) -> dict:
        case = _case_from(state)
        f, t = data_quality.run(case)
        _stamp(t)
        rejected = []
        for d in case.docs:
            if any("Missing required field" in x.message for x in f if d.doc_id in x.evidence_ids):
                rejected.append(d.doc_id)
        return {"findings": f, "trace": t, "rejected_records": rejected}

    def route_after_dq(state: AuditState):
        case = _case_from(state)
        if len(case.docs) == 0:
            return END
        # stop when EVERY document failed the DQ gate
        if len(state.get("rejected_records", [])) >= len(case.docs) > 0:
            return END
        return ["compliance", "anomaly"]

    def n_comp(state: AuditState) -> dict:
        case = _filtered_case(_case_from(state), state.get("rejected_records", []))
        f, t = compliance.run(case, KGClient())
        _stamp(t)
        return {"findings": f, "trace": t}

    def n_anom(state: AuditState) -> dict:
        case = _filtered_case(_case_from(state), state.get("rejected_records", []))
        f, t = anomaly.run(case)
        _stamp(t)
        return {"findings": f, "trace": t}

    def n_reas(state: AuditState) -> dict:
        case = _case_from(state)
        merged, t = reasoning.run(case, list(state.get("findings", [])))
        _stamp(t)
        return {"reasoned": merged, "trace": t}

    def n_val(state: AuditState) -> dict:
        case = _case_from(state)
        base = list(state.get("reasoned", [])) or list(state.get("findings", []))
        kept, rejected, bad_ids, t = evidence_validation.run(case, base)
        _stamp(t)
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


GRAPH = build_graph()  # built once; nodes read case from state


def _initial(case: AuditCase) -> dict:
    return {"case": case.model_dump(), "findings": [], "trace": [],
            "rejected_records": [], "reasoned": [], "final_findings": [],
            "rejected_citations": [], "rejected_findings": []}


def run_case(case: AuditCase, kg: KGClient | None = None) -> AuditResult:
    # kg kept in signature for compat; nodes use default client (mock now, live later)
    out = GRAPH.invoke(_initial(case))
    # BUGFIX: use final_findings directly. Empty list is a valid answer (clean case),
    # never fall back to reasoned/findings or rejected items come back.
    v = VERSION_STORE.get(case.case_id, 0) + 1
    VERSION_STORE[case.case_id] = v
    return AuditResult(case_id=case.case_id, version=v,
                       status=config.FINDINGS_STATUS_DEFAULT,
                       findings=list(out.get("final_findings", [])),
                       trace=list(out.get("trace", [])),
                       rejected_records=list(out.get("rejected_records", [])),
                       rejected_citations=list(out.get("rejected_citations", [])),
                       rejected_findings=list(out.get("rejected_findings", [])))


def stream_case(case: AuditCase, kg: KGClient | None = None):
    """Yield JSON-safe dicts: per-node updates, then one final result event.
    Single graph run: final result built from streamed deltas, version bumped once."""
    acc_findings: list = []
    acc_trace: list = []
    acc_rej_rec: list = []
    acc_rej_cite: list = []
    reasoned: list = []
    final_findings: list = []
    rejected_findings: list = []
    for chunk in GRAPH.stream(_initial(case), stream_mode="updates"):
        safe: dict = {}
        for node, data in chunk.items():
            node_data: dict = {}
            if isinstance(data, dict):
                for k, val in data.items():
                    items = val if isinstance(val, list) else [val]
                    dumps = [x.model_dump() if hasattr(x, "model_dump") else x for x in items]
                    node_data[k] = dumps if isinstance(val, list) else (dumps[0] if dumps else None)
                    # accumulate for final (single run, no re-invoke)
                    if k == "findings" and isinstance(val, list):
                        acc_findings.extend(val)
                    elif k == "trace" and isinstance(val, list):
                        acc_trace.extend(val)
                    elif k == "rejected_records" and isinstance(val, list):
                        acc_rej_rec.extend(val)
                    elif k == "rejected_citations" and isinstance(val, list):
                        acc_rej_cite.extend(val)
                    elif k == "reasoned" and isinstance(val, list):
                        reasoned = val
                    elif k == "final_findings" and isinstance(val, list):
                        final_findings = val
                    elif k == "rejected_findings" and isinstance(val, list):
                        rejected_findings = val
            safe[node] = node_data
        yield {"event": "update", "data": safe}
    v = VERSION_STORE.get(case.case_id, 0) + 1
    VERSION_STORE[case.case_id] = v
    res = AuditResult(case_id=case.case_id, version=v,
                      status=config.FINDINGS_STATUS_DEFAULT,
                      findings=list(final_findings),
                      trace=list(acc_trace),
                      rejected_records=list(acc_rej_rec),
                      rejected_citations=list(acc_rej_cite),
                      rejected_findings=list(rejected_findings))
    yield {"event": "result", "data": res.model_dump()}
