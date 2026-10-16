"""Agent 4: Reasoning — merge findings, fill reasoning_chain for every finding.
Chain steps per finding: which rule, which values, which evidence.
LLM writes the 1-line summary WITH cited IDs; Validation checks the
structured claims in code (not the LLM sentence)."""
from app import config
from app.schemas.case import AuditCase
from app.schemas.findings import Finding, TraceEntry
from app.services import llm


def _chain_for(f: Finding) -> list[str]:
    steps = [f"rule {f.rule_id} ({f.category}, {f.severity})"]
    for c in f.claims:
        steps.append(f"check {c.evidence_id}.{c.field} == {c.claimed_value}")
    steps.append(f"evidence: {', '.join(f.evidence_ids) if f.evidence_ids else 'none'}")
    return steps


def run(case: AuditCase, findings: list[Finding]) -> tuple[list[Finding], list[TraceEntry]]:
    for f in findings:
        if not f.policy_ids and f.rule_id.startswith("CHK"):
            f.policy_ids = [f.rule_id]
        f.reasoning_chain = _chain_for(f)
    cited = sorted({e for f in findings for e in f.evidence_ids})
    cite_text = ", ".join(cited) if cited else "no evidence"
    summary = llm.explain_with_llm(
        f"Say only: case {case.case_id} has {len(findings)} finding(s) citing {cite_text}. No other facts.",
        fallback=f"Case {case.case_id}: {len(findings)} finding(s) citing {cite_text}, all {config.FINDINGS_STATUS_DEFAULT}.")
    trace = [TraceEntry(agent_name="reasoning", decision_type="merge", detail=summary)]
    return findings, trace
