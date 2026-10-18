"""Agent 1: Data Quality, the gatekeeper. Checks in Python; the LLM only narrates.

Returns (findings, rejected_doc_ids, early_stop, trace). A document missing a
required field (CHK-006) or of an unsupported type (REV-002) is rejected: kept
in the result with its finding, excluded from the rule checks. The run stops early when nothing could be checked, and the findings
then say why (never an empty, clean-looking result).
"""
from app import config
from app.schemas.case import AuditCase
from app.schemas.findings import Finding, TraceEntry
from app.services import llm, rules


def run(case: AuditCase) -> tuple[list[Finding], list[str], bool, list[TraceEntry]]:
    if not case.docs:
        f = Finding(finding_id=f"{case.case_id}-CHK006-empty", rule_id="CHK-006",
                    category="format", severity="high", policy_ids=["CHK-006"],
                    message=f"No documents in case {case.case_id}: nothing could be checked.")
        return [f], [], True, [TraceEntry(agent_name="data_quality", decision_type="gate",
                                          detail="Empty case: nothing to check.")]

    findings = rules.data_quality_findings(case)
    incomplete = [d.doc_id for d in case.docs if rules.missing_required(d)]
    unsupported = [d.doc_id for d in case.docs
                   if d.doc_type == "unknown" or d.doc_type not in config.ALLOWED_DOC_TYPES]
    rejected = [d.doc_id for d in case.docs if d.doc_id in incomplete or d.doc_id in unsupported]
    early_stop = len(rejected) == len(case.docs)

    reviews = sum(f.review_status == "needs_more_evidence" for f in findings)
    violations = len(findings) - reviews
    note = llm.narrate(
        f"Say only: data quality found {violations} violation(s) and {reviews} review "
        f"item(s) in {len(case.docs)} document(s).",
        fallback=f"Data quality: {violations} violation(s), {reviews} review item(s) "
                 f"in {len(case.docs)} document(s).")
    trace = [TraceEntry(agent_name="data_quality", decision_type="gate", detail=note)]
    if incomplete:
        trace.append(TraceEntry(agent_name="data_quality", decision_type="reject",
                                detail=f"Rejected (missing required fields): {', '.join(incomplete)}."))
    if unsupported:
        trace.append(TraceEntry(agent_name="data_quality", decision_type="review",
                                detail=f"Unsupported document type, not checked: {', '.join(unsupported)}."))
    if early_stop:
        trace.append(TraceEntry(agent_name="data_quality", decision_type="stop",
                                detail="No document can be checked; the case is not auditable."))
    return findings, rejected, early_stop, trace
