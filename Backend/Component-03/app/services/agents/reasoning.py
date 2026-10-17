"""Agent 4: Reasoning — merge findings, fill reasoning_chain for every finding.
Chain steps per finding: which rule, which values, which evidence.
SO3: the KG policy -> control -> transaction -> evidence chain is appended per
cited document, and a missing-evidence gap becomes a visible CHK-008 review
finding (never hidden). LLM writes the 1-line summary only; Validation checks
the structured claims in code (not the LLM sentence)."""
from app import config
from app.schemas.case import AuditCase
from app.schemas.findings import Finding, TraceEntry
from app.services import llm
from app.services.kg_client import KGClient, KGError


def _chain_for(f: Finding) -> list[str]:
    steps = [f"rule {f.rule_id} ({f.category}, {f.severity})"]
    for c in f.claims:
        steps.append(f"check {c.evidence_id}.{c.field} == {c.claimed_value}")
    steps.append(f"evidence: {', '.join(f.evidence_ids) if f.evidence_ids else 'none'}")
    return steps


def _kg_step(doc_id: str, chain: list[str]) -> str:
    return f"kg chain {doc_id}: {' -> '.join(chain)}"


def _attach_kg_chains(findings: list[Finding], case: AuditCase,
                      kg: KGClient | None) -> dict[str, list[str]]:
    """Append the KG chain to each finding citing a case doc. Returns the
    doc_id -> missing_evidence map for docs whose chain is incomplete."""
    if kg is None:
        return {}
    doc_ids = {d.doc_id for d in case.docs}
    cited = sorted({e for f in findings for e in f.evidence_ids if e in doc_ids})
    chain_text: dict[str, str] = {}
    missing: dict[str, list[str]] = {}
    for doc_id in cited:
        try:
            ec = kg.get_evidence_chain(doc_id)
        except (ValueError, KGError):
            continue  # an unusable chain must never break the audit
        if ec.chain:
            chain_text[doc_id] = _kg_step(doc_id, ec.chain)
        if ec.missing_evidence:
            missing[doc_id] = list(ec.missing_evidence)
    for f in findings:
        for eid in f.evidence_ids:
            step = chain_text.get(eid)
            if step and step not in f.reasoning_chain:
                f.reasoning_chain.append(step)
    return missing


def run(case: AuditCase, findings: list[Finding],
        kg: KGClient | None = None) -> tuple[list[Finding], list[TraceEntry]]:
    for f in findings:
        if not f.policy_ids and f.rule_id.startswith("CHK"):
            f.policy_ids = [f.rule_id]
        f.reasoning_chain = _chain_for(f)

    missing = _attach_kg_chains(findings, case, kg)
    for doc_id, miss in missing.items():
        findings.append(Finding(
            finding_id=f"{doc_id}-CHK008-chain", rule_id="CHK-008",
            category="format", severity="medium",
            message=(f"Evidence chain incomplete for {doc_id}: missing "
                     f"{', '.join(miss)}. More evidence needed."),
            evidence_ids=[doc_id],
            reasoning_chain=["rule CHK-008 (format, medium)",
                             f"evidence: {doc_id}"],
            review_status="needs_more_evidence"))

    for f in findings:
        if f.confidence < config.REVIEW_CONFIDENCE_LIMIT:
            f.review_status = "needs_more_evidence"
    needs_review = [f for f in findings if f.review_status == "needs_more_evidence"]

    cited = sorted({e for f in findings for e in f.evidence_ids})
    cite_text = ", ".join(cited) if cited else "no evidence"
    summary = llm.explain_with_llm(
        f"Say only: case {case.case_id} has {len(findings)} finding(s) citing {cite_text}. No other facts.",
        fallback=f"Case {case.case_id}: {len(findings)} finding(s) citing {cite_text}, all {config.FINDINGS_STATUS_DEFAULT}.")
    trace = [TraceEntry(agent_name="reasoning", decision_type="merge", detail=summary)]
    if needs_review:
        trace.append(TraceEntry(
            agent_name="reasoning", decision_type="review",
            detail=(f"{len(needs_review)} finding(s) need more evidence "
                    f"(low confidence or missing chain).")))
    return findings, trace
