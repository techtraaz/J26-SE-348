"""Agent 4: Reasoning — merge findings, keep pending_auditor_review."""
from app import config
from app.schemas.case import AuditCase
from app.schemas.findings import Finding, TraceEntry
from app.services.llm import explain_with_llm


def run(case: AuditCase, findings: list[Finding]) -> tuple[list[Finding], list[TraceEntry]]:
    for f in findings:
        if not f.policy_ids and f.rule_id.startswith("CHK"):
            f.policy_ids = [f.rule_id]
    summary = explain_with_llm(
        f"Say only: case {case.case_id} has {len(findings)} finding(s). No other facts.",
        fallback=f"Case {case.case_id}: {len(findings)} finding(s), all {config.FINDINGS_STATUS_DEFAULT}.")
    trace = [TraceEntry(agent_name="reasoning", decision_type="merge", detail=summary)]
    return findings, trace
