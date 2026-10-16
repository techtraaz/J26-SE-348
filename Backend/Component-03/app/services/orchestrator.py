"""Full LangGraph flow: DQ -> (Compliance + Anomaly parallel) -> Join -> Reasoning -> Validation."""
import operator
from typing import Annotated, TypedDict
from app import config
from app.schemas.case import AuditCase
from app.schemas.findings import AuditResult
from app.services.agents import data_quality, compliance, anomaly, reasoning, evidence_validation
from app.services.kg_client import KGClient

VERSION_STORE: dict[str, int] = {}  # case_id -> version, old versions kept by caller/DB


class FlowState(TypedDict):
    dq_findings: list
    comp_findings: list
    anom_findings: list
    findings: list  # LastValue: join sets, reasoning keeps, validation replaces
    trace: Annotated[list, operator.add]  # parallel branches only ADD new notes


def run_case(case: AuditCase, kg: KGClient | None = None) -> AuditResult:
    kg = kg or KGClient()
    from langgraph.graph import StateGraph, START, END

    g = StateGraph(FlowState)

    def n_dq(_: FlowState) -> dict:
        f, t = data_quality.run(case)
        return {"dq_findings": f, "trace": t}

    def n_comp(_: FlowState) -> dict:
        f, t = compliance.run(case, kg)
        return {"comp_findings": f, "trace": t}

    def n_anom(_: FlowState) -> dict:
        f, t = anomaly.run(case)
        return {"anom_findings": f, "trace": t}

    def n_join(state: FlowState) -> dict:
        combined = list(state.get("dq_findings", [])) + list(state.get("comp_findings", [])) + list(state.get("anom_findings", []))
        return {"findings": combined}

    def n_reas(state: FlowState) -> dict:
        merged, t = reasoning.run(case, list(state.get("findings", [])))
        return {"findings": merged, "trace": t}

    def n_val(state: FlowState) -> dict:
        final_f, t = evidence_validation.run(case, list(state.get("findings", [])))
        return {"findings": final_f, "trace": t}

    g.add_node("dq", n_dq)
    g.add_node("comp", n_comp)
    g.add_node("anom", n_anom)
    g.add_node("join", n_join)
    g.add_node("reas", n_reas)
    g.add_node("val", n_val)

    g.add_edge(START, "dq")
    g.add_edge("dq", "comp")
    g.add_edge("dq", "anom")
    g.add_edge("comp", "join")
    g.add_edge("anom", "join")
    g.add_edge("join", "reas")
    g.add_edge("reas", "val")
    g.add_edge("val", END)

    app = g.compile()
    out = app.invoke({"dq_findings": [], "comp_findings": [], "anom_findings": [],
                      "findings": [], "trace": []})

    v = VERSION_STORE.get(case.case_id, 0) + 1
    VERSION_STORE[case.case_id] = v
    return AuditResult(case_id=case.case_id, version=v,
                       status=config.FINDINGS_STATUS_DEFAULT,
                       findings=out.get("findings", []), trace=out.get("trace", []))
