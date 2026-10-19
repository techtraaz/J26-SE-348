"""Agent 4: Reasoning. Merges the findings and fills each reasoning_chain:
rule -> KG basis (standard / paragraph) -> values checked -> evidence -> KG links.

SO3: for every cited document the KG evidence chain (linked documents) is read;
a linked document that is not in the case becomes a visible REV-005 review
item. KG lookups that fail are reported in the trace, never hidden. The LLM
writes the one-line summary only.
"""
from app import config
from app.schemas.case import AuditCase, AuditDocument
from app.schemas.findings import Finding, TraceEntry
from app.schemas.kg import RuleExplanation
from app.services import llm, rules
from app.services.kg_client import KGClient, KGError


def _source_step(doc: AuditDocument) -> str:
    s = doc.source
    if s.human_verified:
        who = f" by {s.confirmed_by}" if s.confirmed_by else ""
        return f"source {doc.doc_id}: {s.component.upper()} verified record v{s.verified_version}{who}"
    return f"source {doc.doc_id}: {s.component.upper()} machine extraction, not human-verified"


def _is_kg_rule(rule_id: str) -> bool:
    return rule_id.startswith(("CHK-", "POL-"))


def run(case: AuditCase, findings: list[Finding], kg: KGClient,
        narrate: bool = True) -> tuple[list[Finding], list[TraceEntry]]:
    out = [f.model_copy(deep=True) for f in findings]
    case_ids = {d.doc_id for d in case.docs}
    sources = {d.doc_id: _source_step(d) for d in case.docs if d.source is not None}
    failures: list[str] = []

    explanations: dict[str, RuleExplanation | None] = {}
    for rule_id in sorted({f.rule_id for f in out if _is_kg_rule(f.rule_id)}):
        try:
            explanations[rule_id] = kg.explain_rule(rule_id)
        except (ValueError, KGError) as exc:
            failures.append(f"explain {rule_id} ({exc})")

    links: dict[str, list[str]] = {}
    for doc_id in sorted({e for f in out for e in f.evidence_ids if e in case_ids}):
        try:
            links[doc_id] = [x for x in kg.get_evidence_chain(doc_id) if x != doc_id]
        except (ValueError, KGError) as exc:
            failures.append(f"evidence chain {doc_id} ({exc})")

    for doc_id, linked in links.items():
        absent = [x for x in linked if x not in case_ids]
        if absent:
            out.append(rules.review(
                f"{doc_id}-REV005", "REV-005",
                f"The knowledge graph links {doc_id} to {', '.join(absent)}, which "
                f"{'is' if len(absent) == 1 else 'are'} not in this case. Supply "
                f"{'it' if len(absent) == 1 else 'them'} to complete the evidence chain.",
                [doc_id], severity="medium"))

    for f in out:
        chain = [f"rule {f.rule_id} ({f.category}, {f.severity})"]
        exp = explanations.get(f.rule_id)
        if exp is not None:
            if exp.explanation:
                chain.append(f"basis: {exp.explanation}")
            for ref in (c.ref for c in exp.citations):
                if ref and ref not in f.policy_ids:
                    f.policy_ids.append(ref)
        chain += [f"check {c.evidence_id}.{c.field} = {rules.fmt(c.claimed_value)}"
                  for c in f.claims]
        chain.append(f"evidence: {', '.join(f.evidence_ids) or 'none'}")
        chain += [sources[e] for e in f.evidence_ids if e in sources]
        for e in f.evidence_ids:
            if links.get(e):
                chain.append(f"kg links {e} -> {', '.join(links[e])}")
        f.reasoning_chain = chain
        if f.confidence < config.REVIEW_CONFIDENCE_LIMIT:
            f.review_status = "needs_more_evidence"

    reviews = sum(f.review_status == "needs_more_evidence" for f in out)
    fallback = (f"Case {case.case_id}: {len(out)} finding(s), {reviews} need review, "
                f"all pending auditor review.")
    summary = llm.narrate(
        f"Say only: case {case.case_id} has {len(out)} finding(s), {reviews} need review.",
        fallback=fallback) if narrate else fallback
    trace = [TraceEntry(agent_name="reasoning", decision_type="merge", detail=summary)]
    if failures:
        trace.append(TraceEntry(agent_name="reasoning", decision_type="kg",
                                detail="KG lookup failed, chain left partial: "
                                       + "; ".join(failures) + "."))
    return out, trace
