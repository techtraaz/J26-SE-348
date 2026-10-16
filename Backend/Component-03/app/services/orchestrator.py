"""Full LangGraph hybrid parallel-sequential. Feedback shape: no join node,
conditional stop after DQ, separate overwrite keys, stream for live pills."""
import operator
from typing import Annotated, TypedDict
from app import config
from app.schemas.case import AuditCase
from app.schemas.findings import AuditResult
from app.services.agents import data_quality, compliance, anomaly, reasoning, evidence_validation
from app.services.kg_client import KGClient

VERSION_STORE: dict[str, int] = {}

AGENT_ORDER = ["data_quality", "compliance", "anomaly", "reasoning", "evidence_validation"]


class AuditState(TypedDict):
    case: dict
    findings: Annotated[list, operator.add]  # DQ + Compliance + Anomaly each ADD theirs
    trace: Annotated[list, operator.add]  # every node returns ONLY its own 1 line
    rejected_records: Annotated[list, operator.add]  # DQ rejects, logged not discarded
    reasoned: list  # Reasoning writes here (overwrite)
    final_findings: list  # Validation writes here (overwrite)
    rejected_citations: Annotated[list, operator.add]  # what Validation threw out


def _sort_trace(trace: list) -> list:
    order = {name: i for i, name in enumerate(AGENT_ORDER)}
    return sorted(trace, key=lambda t: order.get(getattr(t, "agent_name", ""), 99))


def build_graph(case: AuditCase, kg: KGClient):
    from langgraph.graph import StateGraph, START, END

    g = StateGraph(AuditState)

    def n_dq(_: AuditState) -> dict:
        f, t = data_quality.run(case)
        # rejected = docs with missing required field (logged, never silently dropped)
        rejected = []
        for d in case.docs:
            if any("Missing required field" in x.message for x in f if d.doc_id in x.evidence_ids):
                rejected.append(d.doc_id)
        return {"findings": f, "trace": t, "rejected_records": rejected}

    def route_after_dq(state: AuditState):
        # FR2: fatal -> stop early and log. Fatal = no docs at all.
        if len(case.docs) == 0:
            return END
        return ["compliance", "anomaly"]

    def n_comp(_: AuditState) -> dict:
        f, t = compliance.run(case, kg)
        return {"findings": f, "trace": t}

    def n_anom(_: AuditState) -> dict:
        f, t = anomaly.run(case)
        return {"findings": f, "trace": t}

    def n_reas(state: AuditState) -> dict:
        # Reasoning LLM writes explanation WITH citations, so Validation has real work.
        merged, t = reasoning.run(case, list(state.get("findings", [])))
        return {"reasoned": merged, "trace": t}

    def n_val(state: AuditState) -> dict:
        base = list(state.get("reasoned", [])) or list(state.get("findings", []))
        final_f, t = evidence_validation.run(case, base)
        kept_ids = {x.finding_id for x in final_f}
        thrown = [x for x in base if x.finding_id not in kept_ids]
        bad_cites = sorted({e for x in thrown for e in x.evidence_ids})
        return {"final_findings": final_f, "trace": t, "rejected_citations": bad_cites}

    g.add_node("data_quality", n_dq)
    g.add_node("compliance", n_comp)
    g.add_node("anomaly", n_anom)
    g.add_node("reasoning", n_reas)
    g.add_node("evidence_validation", n_val)

    g.add_edge(START, "data_quality")
    g.add_conditional_edges("data_quality", route_after_dq)
    # edge list waits for BOTH — no join node needed
    g.add_edge(["compliance", "anomaly"], "reasoning")
    g.add_edge("reasoning", "evidence_validation")
    g.add_edge("evidence_validation", END)
    return g.compile()


def run_case(case: AuditCase, kg: KGClient | None = None) -> AuditResult:
    kg = kg or KGClient()
    app = build_graph(case, kg)
    out = app.invoke({"case": case.model_dump(), "findings": [], "trace": [],
                      "rejected_records": [], "reasoned": [], "final_findings": [],
                      "rejected_citations": []})
    trace = _sort_trace(out.get("trace", []))
    v = VERSION_STORE.get(case.case_id, 0) + 1
    VERSION_STORE[case.case_id] = v
    return AuditResult(case_id=case.case_id, version=v,
                       status=config.FINDINGS_STATUS_DEFAULT,
                       findings=out.get("final_findings", []) or out.get("reasoned", []) or out.get("findings", []),
                       trace=trace,
                       rejected_records=out.get("rejected_records", []),
                       rejected_citations=out.get("rejected_citations", []))


def stream_case(case: AuditCase, kg: KGClient | None = None):
    """Yield one update per finished node for real pills. Frontend calls /audit/run/stream."""
    kg = kg or KGClient()
    app = build_graph(case, kg)
    for chunk in app.stream({"case": case.model_dump(), "findings": [], "trace": [],
                             "rejected_records": [], "reasoned": [], "final_findings": [],
                             "rejected_citations": []},
                            stream_mode="updates"):
        yield chunk
