"""Agent 1: Data Quality — Python checks, LLM only explains."""
from app.schemas.case import AuditCase
from app.schemas.findings import TraceEntry
from app.services import rule_engine
from app.services.llm import explain_with_llm


def run(case: AuditCase) -> tuple[list, list[TraceEntry]]:
    findings = []
    for d in case.docs:
        findings += rule_engine.check_required_fields(d)
    note = explain_with_llm(
        f"Explain in one short line why {len(findings)} data-quality findings exist.",
        fallback=f"Data-quality check found {len(findings)} issue(s).")
    trace = [TraceEntry(agent_name="data_quality", decision_type="gate",
                        detail=note)]
    return findings, trace
