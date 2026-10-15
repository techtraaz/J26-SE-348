"""Agent 3: Anomaly — cross-doc, year jump, cash-without-asset."""
from app.schemas.case import AuditCase
from app.schemas.findings import TraceEntry
from app.services import rule_engine


def run(case: AuditCase) -> tuple[list, list[TraceEntry]]:
    findings = []
    findings += rule_engine.check_parent_amount_match(case)
    findings += rule_engine.check_year_change(case)
    findings += rule_engine.check_cash_without_asset(case)
    trace = [TraceEntry(agent_name="anomaly", decision_type="check",
                        detail=f"Anomaly scan found {len(findings)} issue(s).")]
    return findings, trace
