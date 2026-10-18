"""Agent 1: Data Quality — Python checks, LLM only explains.
Returns (findings, rejected_ids, trace). Empty case produces its own
reason finding here (logic belongs to this agent, not the orchestrator)."""
import re

from app.schemas.case import AuditCase
from app.schemas.findings import Finding, TraceEntry
from app.services import intake, llm, rule_engine

_DOC_IN_ISSUE = re.compile(r"^doc ([^:]+):")


def _issue_doc_id(issue: str) -> str:
    match = _DOC_IN_ISSUE.match(issue)
    return match.group(1) if match else ""


def _issue_rule_id(issue: str) -> str:
    """Map a validate_case issue onto the rule the gate already uses, so an
    issue the gate already reports is not duplicated as a second finding."""
    if "could not be read as a number" in issue:
        return "REV-003"
    if "not supported by the KG" in issue:
        return "REV-002"
    return "REV-004"


def _issue_findings(case: AuditCase, findings: list) -> list[Finding]:
    """Surface intake.validate_case issues as visible review items. Issues the
    gate already reports for the same doc are skipped (one finding per concern)."""
    covered = {(f.evidence_ids[0] if f.evidence_ids else "", f.rule_id)
               for f in findings}
    out: list[Finding] = []
    for i, issue in enumerate(intake.validate_case(case)):
        doc_id = _issue_doc_id(issue)
        rule_id = _issue_rule_id(issue)
        if (doc_id, rule_id) in covered:
            continue
        covered.add((doc_id, rule_id))
        out.append(Finding(
            finding_id=f"{case.case_id}-REV004-{i}", rule_id=rule_id,
            category="format", severity="low", message=issue,
            evidence_ids=[doc_id] if doc_id else [],
            review_status="needs_more_evidence"))
    return out


def run(case: AuditCase) -> tuple[list, list[str], list[TraceEntry]]:
    if len(case.docs) == 0:
        f = [Finding(finding_id=f"{case.case_id}-CHK006-empty", rule_id="CHK-006",
                     category="format", severity="high",
                     message=f"No documents in case {case.case_id}: nothing could be checked.",
                     evidence_ids=[])]
        t = [TraceEntry(agent_name="data_quality", decision_type="gate",
                        detail="Empty case: nothing to check.")]
        return f, [], t
    findings = []
    flagged: list[str] = []
    for d in case.docs:
        findings += rule_engine.check_required_fields(d)
        doctype = rule_engine.check_doc_type(d)
        numbers = rule_engine.check_readable_numbers(d)
        findings += doctype + numbers
        if doctype or numbers:
            flagged.append(d.doc_id)
    findings += _issue_findings(case, findings)
    rejected = rule_engine.rejected_doc_ids(case)
    reviews = [f for f in findings if f.review_status == "needs_more_evidence"]
    violations = len(findings) - len(reviews)
    note = llm.explain_with_llm(
        f"Say only: data-quality findings = {len(findings)} for {len(case.docs)} docs. No other facts.",
        fallback=(f"Data-quality check: {violations} violation(s), "
                  f"{len(reviews)} needs review."))
    trace = [TraceEntry(agent_name="data_quality", decision_type="gate",
                        detail=note)]
    if flagged:
        trace.append(TraceEntry(
            agent_name="data_quality", decision_type="review",
            detail=(f"Unrecognised or unreadable document(s) need review: "
                    f"{', '.join(flagged)}.")))
    return findings, rejected, trace
