"""Agent 4: Reasoning. Merges the findings and fills each reasoning_chain:
rule -> KG basis (standard / paragraph, assertions, risks) -> values checked ->
evidence and its source -> KG links.

SO3: for every cited document the KG evidence chain (linked documents) is read;
a linked document that is not in the case becomes a visible REV-005 review
item. A cited standard that is no longer current (e.g. superseded) is flagged
in the chain, never silently cited. KG lookups run in parallel (each is a
network round trip with the live KG); failures are reported in the trace,
never hidden. The LLM writes the one-line summary only.
"""
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from app import config
from app.schemas.case import AuditCase, AuditDocument
from app.schemas.findings import Finding, TraceEntry
from app.schemas.kg import RuleExplanation, StandardInfo
from app.services import llm, rules, xai_trace
from app.services.kg_client import KGClient, KGError

KG_LOOKUP_WORKERS = 8


def _source_step(doc: AuditDocument) -> str:
    s = doc.source
    if s.human_verified:
        who = f" by {s.confirmed_by}" if s.confirmed_by else ""
        return f"source {doc.doc_id}: {s.component.upper()} verified record v{s.verified_version}{who}"
    return f"source {doc.doc_id}: {s.component.upper()} machine extraction, not human-verified"


def _is_kg_rule(rule_id: str) -> bool:
    return rule_id.startswith(("CHK-", "POL-"))


def _lookup_all(keys: list[str], fetch: Callable[[str], object], what: str,
                failures: list[str]) -> dict[str, object]:
    """fetch(key) for every key at once. A failed lookup is recorded, not raised."""
    def one(key: str):
        try:
            return key, fetch(key), None
        except (ValueError, KGError) as exc:
            return key, None, f"{what} {key} ({exc})"

    if not keys:
        return {}
    with ThreadPoolExecutor(max_workers=min(KG_LOOKUP_WORKERS, len(keys))) as pool:
        results = list(pool.map(one, keys))
    out = {}
    for key, value, error in results:
        if error:
            failures.append(error)
        else:
            out[key] = value
    return out


def _caution(std: StandardInfo) -> str:
    later = f", superseded by {', '.join(std.superseded_by)}" if std.superseded_by else ""
    return f"caution: cited standard {std.code} is {std.status}{later}; check the basis is still current"


def run(case: AuditCase, findings: list[Finding], kg: KGClient,
        narrate: bool = True) -> tuple[list[Finding], list[TraceEntry]]:
    out = [f.model_copy(deep=True) for f in findings]
    case_ids = {d.doc_id for d in case.docs}
    sources = {d.doc_id: _source_step(d) for d in case.docs if d.source is not None}
    failures: list[str] = []

    explanations: dict[str, RuleExplanation | None] = _lookup_all(
        sorted({f.rule_id for f in out if _is_kg_rule(f.rule_id)}), kg.explain_rule, "explain", failures)
    chains = _lookup_all(sorted({e for f in out for e in f.evidence_ids if e in case_ids}),
                         kg.get_evidence_chain, "evidence chain", failures)
    links = {doc_id: [x for x in chain if x != doc_id] for doc_id, chain in chains.items()}
    cited = sorted({c.standard for exp in explanations.values() if exp
                    for c in exp.citations if c.standard})
    standards: dict[str, StandardInfo | None] = _lookup_all(cited, kg.get_standard, "standard", failures)
    outdated = {code: std for code, std in standards.items() if std is not None and not std.current}
    for code, std in standards.items():
        rule_ids = sorted(r for r, exp in explanations.items() if exp and any(
            c.standard == code for c in exp.citations))
        xai_trace.step("standard_check", "passed" if std is None or std.current else "failed",
                       standard=code, title=std.title if std else "",
                       standard_status=std.status if std else "unknown",
                       superseded_by=std.superseded_by if std else [], rule_ids=rule_ids)

    for doc_id, linked in links.items():
        absent = [x for x in linked if x not in case_ids]
        xai_trace.step("evidence_link", "failed" if absent else "passed", doc_id=doc_id,
                       linked=linked, missing=absent)
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
            if exp.assertions:
                chain.append(f"tests: {', '.join(exp.assertions)}")
            if exp.risks:
                chain.append(f"risk: {', '.join(exp.risks)}")
            for c in exp.citations:
                if c.ref and c.ref not in f.policy_ids:
                    f.policy_ids.append(c.ref)
            chain += [_caution(outdated[code]) for code in
                      dict.fromkeys(c.standard for c in exp.citations if c.standard in outdated)]
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
    if outdated:
        trace.append(TraceEntry(agent_name="reasoning", decision_type="kg",
                                detail="Cited standards not current: "
                                       + "; ".join(_caution(s).removeprefix("caution: ")
                                                   for s in outdated.values()) + "."))
    if failures:
        trace.append(TraceEntry(agent_name="reasoning", decision_type="kg",
                                detail="KG lookup failed, chain left partial: "
                                       + "; ".join(sorted(failures)) + "."))
    return out, trace
