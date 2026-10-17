"""Agent 1: Data Quality — Python checks, LLM only explains.
Returns (findings, rejected_ids, trace). Empty case produces its own
reason finding here (logic belongs to this agent, not the orchestrator)."""
from app.schemas.case import AuditCase
from app.schemas.findings import Finding, TraceEntry
from app.services import llm, rule_engine


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
    for d in case.docs:
        findings += rule_engine.check_required_fields(d)
    rejected = rule_engine.rejected_doc_ids(case)
    reviews = [f for f in findings if f.review_status == "needs_more_evidence"]
    violations = len(findings) - len(reviews)
    note = llm.explain_with_llm(
        f"Say only: data-quality findings = {len(findings)} for {len(case.docs)} docs. No other facts.",
        fallback=(f"Data-quality check: {violations} violation(s), "
                  f"{len(reviews)} needs review."))
    trace = [TraceEntry(agent_name="data_quality", decision_type="gate",
                        detail=note)]
    return findings, rejected, trace
