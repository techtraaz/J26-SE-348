"""The chat message an audit leaves, in plain words: what was checked on each
document, what passed, what failed and what needs the auditor.

Built from the saved result in code (every number comes from the rules), so it
reads the same for audits run from the chat and from the Library. The LLM's
case summary, when there is one, is added at the end.
"""
from app.schemas.case import AuditDocument
from app.schemas.findings import AuditResult, Finding, RuleApplication
from app.services.rules import label
from app.services.store import ResultStore

VERDICT = {"clean": "clean", "issues_found": "issues found", "needs_review": "needs review",
           "not_auditable": "not auditable"}
OUTCOME = {"passed": "passed", "failed": "FAILED", "review": "needs your confirmation",
           "skipped": "not checked", "error": "could not be checked"}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _headline(result: AuditResult) -> str:
    broken = [f for f in result.findings if not f.rule_id.startswith("REV-") and f.review_status != "dismissed"]
    reviews = [f for f in result.findings if f.rule_id.startswith("REV-")]
    if broken:
        by = {s: sum(f.severity == s for f in broken) for s in ("high", "medium", "low")}
        sev = ", ".join(f"{n} {s}" for s, n in by.items() if n)
        text = f"{_plural(len(broken), 'rule finding')} ({sev})."
    else:
        text = "No audit rule was broken."
    if reviews:
        text += f" {_plural(len(reviews), 'item')} need{'s' if len(reviews) == 1 else ''} your review."
    return text


def _rule_line(a: RuleApplication) -> str:
    name = f"{a.rule_id} {a.rule_name.rstrip('.')}".strip()
    if a.outcome == "skipped":
        return f"- {name}: not checked ({a.reason})"
    how = f" ({a.detail})" if a.detail else ""
    return f"- {name}: {OUTCOME[a.outcome]}{how}"


def _review_line(f: Finding) -> str:
    return f"- Needs review ({f.rule_id}): {f.message}"


def describe(result: AuditResult, docs: list[AuditDocument]) -> str:
    names = {d.doc_id: label(d) for d in docs}
    head = f"Audit of case {result.case_id} saved as version {result.version}."
    if result.status == "not_auditable":
        reasons = "\n".join(f"- {f.message}" for f in result.findings)
        return f"{head}\nNothing could be checked, so this case is not auditable:\n{reasons}"
    score = f", score {result.score}/100" if result.score is not None else ""
    lines = [f"{head} Verdict: {VERDICT[result.verdict]}{score}.",
             f"{_plural(len(docs), 'document')} checked. {_headline(result)}"]
    for d in docs:
        about = f"{d.doc_type.replace('_', ' ')}, {d.period_year}"
        if d.parent_doc_id:
            about += f", supports {names.get(d.parent_doc_id, d.parent_doc_id)}"
        lines.append(f"\n{names[d.doc_id]} ({about})")
        if d.doc_id in result.rejected_records:
            lines.append("- Left out of the rule checks: its data could not be used (see below).")
        applied = [a for a in result.rules_applied if a.doc_id == d.doc_id]
        ran = [a for a in applied if a.outcome != "skipped"]
        lines += [_rule_line(a) for a in ran]
        skipped = [a for a in applied if a.outcome == "skipped"]
        if skipped:
            lines.append("- Not checked, inputs missing: "
                         + "; ".join(f"{a.rule_id} ({a.reason})" for a in skipped))
        if not applied and d.fields and d.doc_id not in result.rejected_records:
            lines.append("- No audit rules for this document type; only the data checks ran.")
        lines += [_review_line(f) for f in result.findings
                  if f.rule_id.startswith("REV-") and f.evidence_ids[:1] == [d.doc_id]]
    other = [f for f in result.findings if f.rule_id.startswith("REV-")
             and (not f.evidence_ids or f.evidence_ids[0] not in names)]
    if other:
        lines.append("\nAlso needs review:")
        lines += [_review_line(f) for f in other]
    if result.recommendations:
        lines.append("\nWhat to do next")
        lines += [f"- {r.rule_id}: {r.text}" for r in result.recommendations]
    if result.narrative:
        lines.append(f"\nSummary\n{result.narrative}")
    return "\n".join(lines)


def describe_saved(result: AuditResult, store: ResultStore) -> str:
    """describe() with the documents read back from the saved version."""
    rec = store.get(result.case_id, result.version) or {}
    docs = [AuditDocument.model_validate(d) for d in rec.get("case", {}).get("docs", [])]
    return describe(result, docs)
