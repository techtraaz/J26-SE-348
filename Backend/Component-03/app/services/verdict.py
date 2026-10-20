"""The report block of an audit result, decided in plain Python (never the LLM):
verdict, score, a fixed-format summary sentence and one recommendation per finding.

Component-04 builds the PDF report from these fields, so their wording and
meaning only ever grow: new rules get new recommendation text, nothing is renamed.

Score: 100 minus a weight per finding (rule findings by severity, review items a
little), never below 0. A case that could not be audited, or where no rule could
be evaluated, has no score; it is never shown as clean.
"""
from app.schemas.case import AuditDocument
from app.schemas.findings import (
    AuditResult,
    Coverage,
    Finding,
    OpenQuestion,
    Recommendation,
    Verdict,
)

SCORE_WEIGHTS = {"high": 25, "medium": 10, "low": 3}
REVIEW_ITEM_WEIGHT = 2
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

# What to do about a finding, per rule. KG rules (CHK-*, POL-*) first, then C3's
# review items (REV-*). Rules not listed fall back to their category.
RULE_ACTIONS: dict[str, str] = {
    "CHK-001": "Reconcile the statement: find why total assets differ from liabilities plus "
               "equity (unposted or misclassified entries) and correct it.",
    "CHK-002": "Trace the entries that make debits and credits differ and post the correcting entries.",
    "CHK-003": "Compare the supporting document with the one it supports and find out why the "
               "amounts differ before the payment is approved.",
    "CHK-004": "Ask management to explain the large change from the prior year and keep the evidence.",
    "CHK-005": "Possible fraud pattern: confirm the asset was received and recorded, and who "
               "approved the cash payment.",
    "CHK-006": "Obtain the missing details from the source document and complete the record.",
    "CHK-007": "Recheck the current and non-current asset subtotals and correct the classification.",
    "CHK-008": "Recalculate gross profit from revenue and cost of sales and correct the statement.",
    "CHK-009": "Reconcile closing cash in the cash flow statement with cash in the statement of "
               "financial position.",
    "CHK-010": "Reconcile closing equity in the statement of changes in equity with total equity.",
    "CHK-011": "Write inventory down to net realisable value, or document why no write-down is needed.",
    "POL-07": "Get the missing approval signed before payment, and record who approved it and when.",
    "REV-001": "Check the low-confidence value against the source document before relying on it.",
    "REV-002": "Choose the correct document type in the Library, or remove the document from the case.",
    "REV-003": "Check the value on the source document and correct it in the Library.",
    "REV-004": "Check the document was read correctly in the Library; if it has no amounts, keep it "
               "as supporting evidence.",
    "REV-005": "Add the linked documents to the case so the evidence chain is complete.",
    "REV-006": "Check this rule by hand on the document.",
    "REV-007": "Re-run the audit when the knowledge graph is available.",
    "REV-008": "Have the document verified in Component-01's review before relying on it.",
}
# A finding that asks the auditor to confirm (medium POL-07: approvals not read) gets this instead.
CONFIRM_ACTIONS: dict[str, str] = {
    "POL-07": "Confirm the required approvals are signed on the document (the approval stamp "
              "could not be read).",
}
CATEGORY_ACTIONS: dict[str, str] = {
    "arithmetic": "Recalculate the figures named in the finding and correct them.",
    "ledger": "Trace the ledger entries behind the figures and post the corrections.",
    "compliance": "Obtain the evidence the policy requires, or record why it does not apply.",
    "possible_fraud": "Investigate the transaction with management and keep the evidence.",
    "format": "Check the document in the Library and correct what was read.",
}


def _is_review(f: Finding) -> bool:
    return f.rule_id.startswith("REV-")


def verdict_of(result: AuditResult) -> Verdict:
    if result.status == "not_auditable":
        return "not_auditable"
    if any(not _is_review(f) for f in result.findings):
        return "issues_found"
    if result.findings or _nothing_checked(result):
        return "needs_review"  # never "clean" when no rule could actually be evaluated
    return "clean"


def _nothing_checked(result: AuditResult) -> bool:
    """Rules applied, but none could be evaluated (all lacked values)."""
    return bool(result.rules_applied) and all(a.outcome == "skipped" for a in result.rules_applied)


def score_of(result: AuditResult) -> int | None:
    if result.status == "not_auditable" or _nothing_checked(result):
        return None  # no score is better than a perfect score for an audit that checked nothing
    lost = sum(REVIEW_ITEM_WEIGHT if _is_review(f) else SCORE_WEIGHTS[f.severity] for f in result.findings)
    return max(0, 100 - lost)


def _action(f: Finding, confirm: bool) -> str:
    if confirm and f.rule_id in CONFIRM_ACTIONS:
        return CONFIRM_ACTIONS[f.rule_id]
    return RULE_ACTIONS.get(f.rule_id) or CATEGORY_ACTIONS[f.category]


def recommendations_of(result: AuditResult) -> list[Recommendation]:
    """One per finding, most severe first."""
    asks = {a.finding_id for a in result.rules_applied if a.outcome == "review" and a.finding_id}
    ordered = sorted(result.findings, key=lambda f: (SEVERITY_ORDER[f.severity], _is_review(f)))
    return [Recommendation(finding_id=f.finding_id, rule_id=f.rule_id, severity=f.severity,
                           text=_action(f, f.finding_id in asks)) for f in ordered]


def _count(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def summary_of(result: AuditResult, doc_count: int) -> str:
    """One sentence, always in this shape, e.g. '3 documents audited; 4 rule checks:
    3 passed, 1 failed; 1 rule finding (1 high), 0 review items.'"""
    if result.status == "not_auditable":
        return (f"{_count(doc_count, 'document')} received; nothing could be checked "
                f"({_count(len(result.findings), 'reason')}).")
    outcomes = [a.outcome for a in result.rules_applied]
    checked = [o for o in outcomes if o != "skipped"]
    parts = [f"{n} {word}" for word, n in (
        ("passed", checked.count("passed")), ("failed", checked.count("failed")),
        ("need confirmation", checked.count("review")), ("could not be evaluated", checked.count("error")))
        if n]
    rule = [f for f in result.findings if not _is_review(f)]
    sev = ", ".join(f"{n} {s}" for s in ("high", "medium", "low")
                    if (n := sum(f.severity == s for f in rule)))
    text = (f"{_count(doc_count, 'document')} audited; {_count(len(checked), 'rule check')}"
            f"{': ' + ', '.join(parts) if parts else ''}")
    skipped = outcomes.count("skipped")
    if skipped:
        text += f" ({skipped} not run, inputs missing)"
    text += (f"; {_count(len(rule), 'rule finding')}{f' ({sev})' if sev else ''}, "
             f"{_count(len(result.findings) - len(rule), 'review item')}.")
    return text


def coverage_of(result: AuditResult) -> Coverage:
    counts = {o: sum(a.outcome == o for a in result.rules_applied)
              for o in ("passed", "failed", "review", "error", "skipped")}
    run = counts["passed"] + counts["failed"] + counts["review"] + counts["error"]
    return Coverage(rules_run=run, passed=counts["passed"], failed=counts["failed"], review=counts["review"],
                    error=counts["error"], not_run=counts["skipped"],
                    complete=counts["skipped"] == 0 and counts["error"] == 0
                    and result.status != "not_auditable")


def _words(fields: list[str]) -> str:
    names = [f.replace("_", " ") for f in fields]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def open_questions_of(result: AuditResult, docs: list[AuditDocument]) -> list[OpenQuestion]:
    """One question per rule that could not run for lack of values on its own document.
    Inputs from another document (child., parent., prior.) need a link or a document,
    not a value, so they are not asked here."""
    names = {d.doc_id: d.name or d.doc_id for d in docs}
    out = []
    for a in result.rules_applied:
        own = [m for m in a.missing_inputs if "." not in m]
        if a.outcome != "skipped" or not own:
            continue
        doc = names.get(a.doc_id, a.doc_id)
        rule = f"{a.rule_id} {a.rule_name}".strip()
        verb = "is" if len(own) == 1 else "are"
        out.append(OpenQuestion(
            doc_id=a.doc_id, doc_name=doc, rule_id=a.rule_id, rule_name=a.rule_name, missing=own,
            question=f"{rule} could not run on {doc}: it needs the {_words(own)}. "
                     f"What {verb} the {_words(own)} on this document?"))
    return out


def fill(result: AuditResult, docs: list[AuditDocument]) -> AuditResult:
    """Set the report block on a finished result (called once, before it is saved)."""
    result.verdict = verdict_of(result)
    result.score = score_of(result)
    result.coverage = coverage_of(result)
    result.open_questions = open_questions_of(result, docs)
    result.summary = summary_of(result, len(docs))
    result.narrative = next((t.detail for t in result.trace if t.decision_type == "summary"), None)
    result.recommendations = recommendations_of(result)
    return result
