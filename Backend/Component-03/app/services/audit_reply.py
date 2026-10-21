"""The chat message an audit leaves, as reply blocks: the verdict, what was checked
on each document, what passed, what failed, what could not be checked and why,
what needs the auditor, and what to do next. Materiality is asked for only when it
would change something: an amount comparison failed and the case has none.

Built from the saved result in code (every number comes from the rules), so it
reads the same for audits run from the chat and from the Library. The LLM's
case summary, when there is one, comes last.
"""
from app.schemas.case import AuditDocument
from app.schemas.copilot import (
    Block,
    ListBlock,
    ListItem,
    QuestionBlock,
    TextBlock,
    VerdictBlock,
)
from app.schemas.findings import AuditResult, RuleApplication
from app.services.copilot.render import to_markdown
from app.services.expression import amount_difference
from app.services.rules import fmt, label
from app.services.store import ResultStore


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _headline(result: AuditResult, doc_count: int) -> str:
    broken = [f for f in result.findings if not f.rule_id.startswith("REV-")]
    reviews = [f for f in result.findings if f.rule_id.startswith("REV-")]
    if broken:
        by = {s: sum(f.severity == s for f in broken) for s in ("high", "medium", "low")}
        sev = ", ".join(f"{n} {s}" for s, n in by.items() if n)
        text = f"{_plural(len(broken), 'rule finding')} ({sev})."
    else:
        text = "No audit rule was broken."
    if reviews:
        text += f" {_plural(len(reviews), 'item')} need{'s' if len(reviews) == 1 else ''} your review."
    return f"{_plural(doc_count, 'document')} checked. {text}"


def _rule_item(a: RuleApplication) -> ListItem:
    name = f"{a.rule_id} {a.rule_name.rstrip('.')}".strip()
    return ListItem(label=name, text=a.detail, tone=a.outcome)


def describe_blocks(result: AuditResult, docs: list[AuditDocument],
                    materiality: float | None = None) -> list[Block]:
    names = {d.doc_id: label(d) for d in docs}
    verdict = VerdictBlock(case_id=result.case_id, version=result.version, verdict=result.verdict,
                           score=result.score, summary=_headline(result, len(docs)))
    if result.status == "not_auditable":
        return [verdict, ListBlock(title="Nothing could be checked", items=[
            ListItem(label=f.rule_id, text=f.message, tone="failed") for f in result.findings])]
    blocks: list[Block] = [verdict]
    cov = result.coverage
    if not cov.complete and cov.not_run:
        blocks.append(TextBlock(text=f"**Limited check:** {cov.not_run} of {cov.rules_run + cov.not_run} "
                                     f"rules could not run because values are missing, so this verdict may "
                                     f"miss a problem those rules look for."))
    for d in docs:
        about = f"{d.doc_type.replace('_', ' ')}, {d.period_year}"
        if d.parent_doc_id:
            about += f", supports {names.get(d.parent_doc_id, d.parent_doc_id)}"
        items: list[ListItem] = []
        if d.doc_id in result.rejected_records:
            items.append(ListItem(label="Left out of the rule checks",
                                  text="its data could not be used (see the review items)", tone="failed"))
        applied = [a for a in result.rules_applied if a.doc_id == d.doc_id]
        items += [_rule_item(a) for a in applied if a.outcome != "skipped"]
        skipped = [a for a in applied if a.outcome == "skipped"]
        if skipped:
            items.append(ListItem(label="Not checked", text="inputs missing", tone="skipped",
                                  details=[f"{a.rule_id}: {a.reason}" for a in skipped]))
        if not applied and d.fields and d.doc_id not in result.rejected_records:
            items.append(ListItem(label="No audit rules for this document type",
                                  text="only the data checks ran"))
        items += [ListItem(label=f"Needs review ({f.rule_id})", text=f.message, tone="review")
                  for f in result.findings if f.rule_id.startswith("REV-") and f.evidence_ids[:1] == [d.doc_id]]
        blocks.append(ListBlock(title=f"{names[d.doc_id]} ({about})", items=items))
    other = [f for f in result.findings if f.rule_id.startswith("REV-")
             and (not f.evidence_ids or f.evidence_ids[0] not in names)]
    if other:
        blocks.append(ListBlock(title="Also needs review", items=[
            ListItem(label=f.rule_id, text=f.message, tone="review") for f in other]))
    if result.recommendations:
        blocks.append(ListBlock(title="What to do next", items=[
            ListItem(label=r.rule_id, text=r.text, tone=r.severity) for r in result.recommendations]))
    blocks += open_questions_blocks(result)
    if materiality is None:
        blocks += materiality_question(result, names)
    if result.narrative:
        blocks.append(TextBlock(text=f"**Summary**\n\n{result.narrative}"))
    return blocks


def open_questions_blocks(result: AuditResult) -> list[Block]:
    """Ask for the values that would let the skipped rules run."""
    if not result.open_questions:
        return []
    first = result.open_questions[0]
    example = f"“{first.missing[0].replace('_', ' ')} on {first.doc_name} is …”"
    return [ListBlock(title="To complete the audit, tell me", items=[
                ListItem(label=q.doc_name, text=q.question) for q in result.open_questions[:10]],
                more=max(0, len(result.open_questions) - 10)),
            TextBlock(text=f"Reply with the value, for example {example}.")]


def materiality_question(result: AuditResult, names: dict[str, str]) -> list[Block]:
    """Offer materiality only after a plain amount comparison failed (fraud patterns,
    ratios and policy limits have no amount difference, so they never trigger it)."""
    gaps = [(gap, a) for a in result.rules_applied if a.outcome == "failed" and a.kind == "rule_check"
            and (gap := amount_difference(a.expression or "", a.values)) is not None]
    if not gaps:
        return []
    gap, a = max(gaps, key=lambda g: g[0])
    return [QuestionBlock(text=(
        f"**{a.rule_id}** on {names.get(a.doc_id, a.doc_id)} is off by **{fmt(gap)}**. Are differences below "
        f"some amount too small to matter for this audit? Tell me the amount, for example “ignore differences "
        f"below 50,000”, and smaller ones will be marked minor (auditors call this amount *materiality*). "
        f"They stay listed; fraud patterns and policy limits are never softened."),
        choices=["What is materiality?"])]


def describe(result: AuditResult, docs: list[AuditDocument], materiality: float | None = None) -> str:
    return to_markdown(describe_blocks(result, docs, materiality))


def _saved_case(result: AuditResult, store: ResultStore) -> dict:
    return (store.get(result.case_id, result.version) or {}).get("case", {})


def saved_docs(result: AuditResult, store: ResultStore) -> list[AuditDocument]:
    """The documents of the saved version."""
    return [AuditDocument.model_validate(d) for d in _saved_case(result, store).get("docs", [])]


def describe_saved(result: AuditResult, store: ResultStore) -> str:
    return describe(result, saved_docs(result, store), _saved_case(result, store).get("materiality"))


def describe_saved_blocks(result: AuditResult, store: ResultStore) -> list[Block]:
    return describe_blocks(result, saved_docs(result, store), _saved_case(result, store).get("materiality"))
