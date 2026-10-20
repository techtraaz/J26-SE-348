"""Agent 1: Data Quality, the gatekeeper. Checks in Python, no LLM.

Returns (findings, rejected_doc_ids, early_stop, trace). A document missing a
required field (CHK-006) or of an unsupported type (REV-002) is rejected: kept
in the result with its finding, excluded from the rule checks. The run stops
early when nothing could be checked, and the findings then say why (never an
empty, clean-looking result).
"""
from app import config
from app.schemas.case import AuditCase
from app.schemas.findings import Finding, TraceEntry
from app.services import rules, xai_trace


def _trace_read(doc) -> None:
    """XAI: what was read from one document, and where its values came from."""
    src = doc.source
    xai_trace.step(
        "evidence_read", "ok", doc_id=doc.doc_id, doc_type=doc.doc_type,
        period_year=doc.period_year, parent_doc_id=doc.parent_doc_id,
        field_count=len(doc.fields),
        fields={k: v for k, v in list(doc.fields.items())[:12]},
        min_confidence=min(doc.confidences.values()) if doc.confidences else None,
        source=src.component if src else None,
        verified_version=src.verified_version if src else None,
        confirmed_by=src.confirmed_by if src else None,
        methods=sorted(set(doc.methods.values()))[:5])


def _trace_findings(case: AuditCase, findings: list[Finding]) -> None:
    """XAI: one dq_check per document (passed when clean), one per problem found."""
    flagged = {e for f in findings for e in f.evidence_ids}
    for d in case.docs:
        if d.doc_id not in flagged:
            xai_trace.step("dq_check", "passed", doc_id=d.doc_id, doc_type=d.doc_type,
                           check="required fields present and readable")
    for f in findings:
        xai_trace.step("dq_check", "review" if f.review_status == "needs_more_evidence" else "failed",
                       rule_id=f.rule_id, doc_id=", ".join(f.evidence_ids),
                       severity=f.severity, reason=f.message)


def run(case: AuditCase) -> tuple[list[Finding], list[str], bool, list[TraceEntry]]:
    if not case.docs:
        f = Finding(finding_id=f"{case.case_id}-CHK006-empty", rule_id="CHK-006",
                    category="format", severity="high", policy_ids=["CHK-006"],
                    message=f"No documents in case {case.case_id}: nothing could be checked.")
        return [f], [], True, [TraceEntry(agent_name="data_quality", decision_type="gate",
                                          detail="Empty case: nothing to check.")]

    for d in case.docs:
        _trace_read(d)
    findings = rules.data_quality_findings(case)
    _trace_findings(case, findings)
    incomplete = [d.doc_id for d in case.docs if rules.missing_required(d)]
    unsupported = [d.doc_id for d in case.docs
                   if d.doc_type == "unknown" or d.doc_type not in config.ALLOWED_DOC_TYPES]
    rejected = [d.doc_id for d in case.docs if d.doc_id in incomplete or d.doc_id in unsupported]
    early_stop = len(rejected) == len(case.docs)

    reviews = sum(f.review_status == "needs_more_evidence" for f in findings)
    violations = len(findings) - reviews
    note = (f"Data quality: {violations} violation(s), {reviews} review item(s) "
            f"in {len(case.docs)} document(s).")
    trace = [TraceEntry(agent_name="data_quality", decision_type="gate", detail=note)]
    if incomplete:
        trace.append(TraceEntry(agent_name="data_quality", decision_type="reject",
                                detail=f"Rejected (missing required fields): {', '.join(incomplete)}."))
    if unsupported:
        trace.append(TraceEntry(agent_name="data_quality", decision_type="review",
                                detail=f"Unsupported document type, not checked: {', '.join(unsupported)}."))
    for doc_id in rejected:
        xai_trace.step("decision", "failed", decision="document excluded from rule checks",
                       doc_id=doc_id,
                       reason="missing required fields" if doc_id in incomplete
                       else "document type not supported")
    if early_stop:
        xai_trace.step("decision", "failed", decision="audit stopped",
                       reason="no document can be checked; the case is not auditable")
        trace.append(TraceEntry(agent_name="data_quality", decision_type="stop",
                                detail="No document can be checked; the case is not auditable."))
    return findings, rejected, early_stop, trace
