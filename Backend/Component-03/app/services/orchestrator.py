"""Hybrid flow: DQ -> (Compliance + Anomaly in parallel via LangGraph) -> Reasoning -> Validation."""
import operator
from typing import Annotated, TypedDict
from app import config
from app.schemas.case import AuditCase
from app.schemas.findings import AuditResult
from app.services.agents import data_quality, compliance, anomaly, reasoning, evidence_validation
from app.services.kg_client import KGClient

VERSION_STORE: dict[str, int] = {}  # case_id -> version, old versions kept by caller/DB


class FlowState(TypedDict):
    findings: Annotated[list, operator.add]
    trace: Annotated[list, operator.add]


def run_case(case: AuditCase, kg: KGClient | None = None) -> AuditResult:
    """DQ runs first, then comp+anom truly parallel in LangGraph, then reas+val."""
    kg = kg or KGClient()
    from langgraph.graph import StateGraph, START, END

    g = StateGraph(FlowState)

    def n_dq(_: FlowState) -> dict:
        f, t = data_quality.run(case)
        return {"findings": f, "trace": t}

    def n_comp(_: FlowState) -> dict:
        f, t = compliance.run(case, kg)
        return {"findings": f, "trace": t}

    def n_anom(_: FlowState) -> dict:
        f, t = anomaly.run(case)
        return {"findings": f, "trace": t}

    def n_join(_: FlowState) -> dict:
        return {}

    g.add_node("dq", n_dq)
    g.add_node("comp", n_comp)
    g.add_node("anom", n_anom)
    g.add_node("join", n_join)

    g.add_edge(START, "dq")
    g.add_edge("dq", "comp")
    g.add_edge("dq", "anom")
    g.add_edge("comp", "join")
    g.add_edge("anom", "join")
    g.add_edge("join", END)

    app = g.compile()
    out = app.invoke({"findings": [], "trace": []})
    parallel_findings: list = out.get("findings", [])
    parallel_trace: list = out.get("trace", [])

    # Sequential tail: reasoning merges, validation drops bad citations.
    merged, reas_t = reasoning.run(case, list(parallel_findings))
    final_findings, val_t = evidence_validation.run(case, merged)
    full_trace = list(parallel_trace) + list(reas_t) + list(val_t)

    v = VERSION_STORE.get(case.case_id, 0) + 1
    VERSION_STORE[case.case_id] = v
    return AuditResult(case_id=case.case_id, version=v,
                       status=config.FINDINGS_STATUS_DEFAULT,
                       findings=final_findings, trace=full_trace)
