"""Copilot intent handlers. One decorated function per intent; registration
order is the tie-break order of the rules classifier (more specific first).

Every reply is built from stored results or KG data in code. The LLM never
writes a reply and never decides a verdict.
"""
import re
from collections import Counter
from dataclasses import dataclass, field

from app import config
from app.schemas.copilot import (
    CopilotQuery,
    FindingsBlock,
    LinkBlock,
    ListBlock,
    ListItem,
    QuestionBlock,
    TableBlock,
    TextBlock,
    VerdictBlock,
)
from app.services import audit_reply, c4_report, intake, orchestrator
from app.services import rules as rules_mod
from app.services.copilot import whatif
from app.services.copilot.entities import Entities
from app.services.copilot.registry import REGISTRY, intent
from app.services.kg_client import KGClient
from app.services.rules import fmt
from app.services.store import MemoryStore, ResultStore

MAX = config.COPILOT_MAX_ITEMS


@dataclass
class Turn:
    """Everything a handler may use for one request."""
    query: CopilotQuery
    entities: Entities
    kg: KGClient
    store: ResultStore
    case_id: str | None
    _records: dict = field(default_factory=dict)

    def record(self, version: int | None = None) -> dict | None:
        key = version or "latest"
        if key not in self._records:
            self._records[key] = (self.store.get(self.case_id, version) if version
                                  else self.store.latest(self.case_id))
        return self._records[key]


@dataclass
class Reply:
    """A handler's answer: blocks (preferred; the text is rendered from them) or plain text."""
    text: str = ""
    data: dict | None = None
    blocks: list = field(default_factory=list)


# --- formatting --------------------------------------------------------------

def _is_review(f: dict) -> bool:
    return f["rule_id"].startswith("REV-") or f["review_status"] == "needs_more_evidence"


def _counts(findings: list[dict]) -> str:
    violations = [f for f in findings if not f["rule_id"].startswith("REV-")]
    sev = Counter(f["severity"] for f in violations)
    reviews = sum(_is_review(f) for f in findings)
    return (f"{len(violations)} rule finding(s) (high {sev['high']}, medium {sev['medium']}, "
            f"low {sev['low']}), {reviews} need review")


def _doc_types(rec: dict) -> dict[str, str]:
    return {d["doc_id"]: d["doc_type"] for d in rec.get("case", {}).get("docs", [])}


def _filter(findings: list[dict], e: Entities, rec: dict) -> list[dict]:
    types = _doc_types(rec)
    out = []
    for f in findings:
        if e.finding_ids and f["finding_id"] not in e.finding_ids:
            continue
        if e.severities and f["severity"] not in e.severities:
            continue
        if e.rule_ids and f["rule_id"] not in e.rule_ids:
            continue
        if e.categories and f["category"] not in e.categories:
            continue
        if e.review_statuses and f["review_status"] not in e.review_statuses:
            continue
        if e.doc_ids and not set(e.doc_ids) & set(f["evidence_ids"]):
            continue
        if e.doc_types and not {types.get(d) for d in f["evidence_ids"]} & set(e.doc_types):
            continue
        out.append(f)
    return out


def _names(rec: dict) -> dict[str, str]:
    """doc_id -> what people call the document (its file name when known)."""
    return {d["doc_id"]: d.get("name") or d["doc_id"] for d in rec.get("case", {}).get("docs", [])}


def _on(f: dict, names: dict[str, str]) -> str:
    return ", ".join(names.get(e, e) for e in f["evidence_ids"]) or "the case"


def _findings_block(title: str, findings: list[dict]) -> FindingsBlock:
    shown = findings[:MAX]
    lines = []
    for f in shown:
        flag = " (citation failed)" if f.get("citation_unverified") else ""
        lines.append(f"{f['rule_id']} · {f['severity']}{flag}: {f['message']}")
    return FindingsBlock(title=title, finding_ids=[f["finding_id"] for f in shown], lines=lines,
                         more=max(0, len(findings) - MAX))


def _doc_words(doc_type: str) -> str:
    return doc_type.replace("_", " ")


# A reasoning-chain step "basis: ..." shown as a labelled point.
_STEP_LABELS = {"rule": "Rule", "basis": "Basis", "tests": "Tests", "risk": "Risk", "check": "Value checked",
                "evidence": "Evidence", "source": "Source", "kg links": "Linked in the KG",
                "caution": "Caution"}


def _step(step: str, names: dict[str, str]) -> ListItem:
    """One reasoning-chain step, with document ids shown as their names."""
    for prefix, label in _STEP_LABELS.items():
        if step.startswith((prefix + " ", prefix + ":")):
            text = step[len(prefix):].lstrip(": ")
            if prefix == "check":  # "DOC.field = value"
                doc_id, _, rest = text.partition(".")
                text = f"{names.get(doc_id, doc_id)} · {rest}" if rest else text
            elif prefix == "evidence":
                text = ", ".join(names.get(e.strip(), e.strip()) for e in text.split(","))
            elif prefix == "source":  # "DOC: C1 verified record v1"
                doc_id, sep, rest = text.partition(": ")
                text = f"{names.get(doc_id, doc_id)}: {rest}" if sep else text
            return ListItem(label=label, text=text)
    return ListItem(label="Note", text=step)


def _rule_facts(kg: KGClient, rule_id: str) -> tuple[object | None, list[str]]:
    """The KG rule (check or policy) and the document types it applies to."""
    found, types = None, []
    for doc_type in sorted(config.ALLOWED_DOC_TYPES - {"unknown"}):
        rules = [*kg.get_check_rules(doc_type), *kg.get_rules(doc_type)]
        hit = next((r for r in rules if r.rule_id == rule_id), None)
        if hit is not None:
            found = found or hit
            types.append(doc_type)
    return found, types


def _rule_item(rule) -> ListItem:
    """One rule as a list item: what it checks, its severity or limit."""
    if hasattr(rule, "expression"):
        return ListItem(label=f"{rule.rule_id} {rule.name}".strip(), text=f"checks `{rule.expression}`",
                        tone=rule.severity)
    need = rules_mod.required_approvals(rule)
    limit = f"limit Rs {fmt(float(rule.limit))}" if rule.limit is not None else "no limit set"
    approvals = f", needs {need} approvals" if need else ""
    return ListItem(label=rule.rule_id, text=f"{rule.text.rstrip('.')} ({limit}{approvals})")


def _audit_reply(result, store: ResultStore) -> Reply:
    return Reply(blocks=audit_reply.describe_saved_blocks(result, store), data=result.model_dump())


# --- what-if and audits (fresh_audit / evidence_append) ----------------------------

@intent("whatif_check", group="fresh_audit",
        description="Check a transaction the user describes in words (amounts in the text, "
                    "no documents attached) against the audit rules, without saving.",
        examples=("I paid Rs 150,000 cash for a laptop but booked it on credit, is that ok?",
                  "what if an invoice of 250,000 has only one approval?"),
        patterns={r"\bis (that|this|it) (ok|okay|fine|allowed|compliant|correct|right|legal)\b": 2.0,
                  r"\bwhat if\b": 2.0, r"\b(paid|bought|booked|purchased|spent|recorded)\b": 1.0,
                  r"\bshould (i|we)\b": 0.5},
        signals={"amounts": 1.0, "docs": -3.0}, needs=("text_values",),
        follow_ups=("What is the dual approval limit for invoices?", "Explain CHK-005"))
def whatif_check(turn: Turn) -> Reply:
    doc, read = whatif.build_document(turn.query.text, turn.entities)
    if not read["fields"]:
        return Reply("I could not match the amounts to document fields. Say what each amount "
                     "is, e.g. 'invoice amount Rs 150,000, paid in cash'.", {"read": read})
    case = intake.normalize_case({"case_id": "WHATIF", "docs": [doc]})
    result = orchestrator.run_case(case, turn.kg, store=MemoryStore(), narrate=False)
    findings = [f.model_dump() for f in result.findings]
    rule_findings = [f for f in findings if not f["rule_id"].startswith("REV-")]
    read_items = [ListItem(label=k.replace("_", " "), text=fmt(v) if isinstance(v, float) else str(v))
                  for k, v in read["fields"].items()]
    blocks = [TextBlock(text=f"What-if check on a {_doc_words(read['doc_type'])} (not saved)."),
              ListBlock(title="I read these values (correct me if one is wrong)", items=read_items)]
    blocks.append(_findings_block("Rules that would fail", rule_findings) if rule_findings
                  else TextBlock(text="No audit rule failed for these values."))
    return Reply(blocks=blocks, data={"read": read, "findings": rule_findings, "unsaved": True,
                                      "result": result.model_dump()})


@intent("evidence_append", group="evidence_append",
        description="Add new documents to an existing audited case and re-run it as a new version.",
        examples=("add this receipt to case CASE-7", "attach the bank statement to the case"),
        patterns={r"\b(add(ing)?|append|attach|upload|include)\b": 2.0,
                  r"\b(more|new|another|extra) (evidence|documents?|invoices?|receipts?|bills?|statements?)\b": 1.5},
        signals={"docs": 1.0, "docs_for_audited_case": 3.5}, needs=("saved_case", "docs"),
        follow_ups=("Show the high severity findings", "What evidence is missing?", "What changed since the last audit?"))
def evidence_append(turn: Turn) -> Reply:
    result = orchestrator.append_evidence(turn.case_id, turn.query.docs, turn.kg, store=turn.store)
    return _audit_reply(result, turn.store)


@intent("fresh_audit", group="fresh_audit",
        description="Run a new audit on the documents attached to the request.",
        examples=("audit these documents", "run a fresh audit on this year's books"),
        patterns={r"\b(fresh|new) audit\b": 2.5, r"\bfrom scratch\b": 2.0,
                  r"\b(audit|check|review|analy[sz]e|examine|verify)\b": 1.0,
                  r"\b(these|this|attached) (documents?|docs|files|books|records)\b": 1.5},
        signals={"docs": 2.0, "docs_for_audited_case": -1.5}, needs=("case", "docs"),
        instead={"docs": "rerun_audit"},
        follow_ups=("Show the high severity findings", "What evidence is missing?", "Summarise this case"))
def fresh_audit(turn: Turn) -> Reply:
    case = intake.normalize_case({"case_id": turn.case_id, "docs": turn.query.docs})
    result = orchestrator.run_case(case, turn.kg, store=turn.store)
    return _audit_reply(result, turn.store)


@intent("rerun_audit", group="fresh_audit",
        description="Run an already audited case again on its latest documents (e.g. after the "
                    "rules changed), saving a new version.",
        examples=("re-run case CASE-7", "audit case ACME-1 again with the new rules"),
        patterns={r"\bre-?run\b": 2.5, r"\b(again|once more)\b": 1.5, r"\bre-?audit\b": 2.0,
                  r"\b(audit|check|run|do)\b.*\b(again|once more)\b": 1.5},
        signals={"case_ids": 0.5, "docs": -1.0}, needs=("saved_case",),
        follow_ups=("What changed since the last audit?", "Show the high severity findings"))
def rerun_audit(turn: Turn) -> Reply:
    case = intake.normalize_case(turn.record()["case"])
    result = orchestrator.run_case(case, turn.kg, store=turn.store)
    return _audit_reply(result, turn.store)


# --- questions about saved audits (case_query) ---------------------------------------

@intent("explain_finding", group="case_query",
        description="Explain why a specific finding was raised in a case: the rule, the values "
                    "checked, the evidence and its validation.",
        examples=("why did CHK-004 fire on case ABC-1?", "explain the POL-07 finding on INV-9"),
        patterns={r"\bwhy\b": 1.5, r"\b(fired|flagged|raised|triggered|failed)\b": 1.5,
                  r"\breason(ing)?\b": 1.0, r"\bexplain\b": 0.5, r"\bfinding\b": 1.0},
        signals={"rule_ids": 1.0, "doc_ids": 1.0, "case_ids": 1.0, "finding_ids": 1.5},
        needs=("saved_case",),
        follow_ups=("Show the findings that need review", "What evidence is missing?"))
def explain_finding(turn: Turn) -> Reply:
    rec = turn.record()
    names = _names(rec)
    e = turn.entities
    matches = _filter(rec["findings"], e, rec)
    narrowed = any((e.rule_ids, e.doc_ids, e.finding_ids, e.doc_types, e.severities, e.categories))
    if not matches:
        return Reply(f"No finding in case {turn.case_id} (version {rec['version']}) matches that.")
    if len(matches) > 1 and not narrowed:
        choices = [f"Why was {f['rule_id']} raised on {_on(f, names)}?" for f in matches[:5]]
        return Reply(blocks=[QuestionBlock(text=f"Case {turn.case_id} has {len(matches)} findings. "
                                                f"Which one should I explain?", choices=choices)],
                     data={"version": rec["version"]})
    reasons = {r["finding"]["finding_id"]: r["reason"] for r in rec.get("rejected_findings", [])}
    blocks = []
    for f in matches[:3]:
        items = [_step(s, names) for s in f["reasoning_chain"][1:]]
        items.append(ListItem(label="Confidence", text=f"{f['confidence']:.2f} · review status "
                                                       f"{f['review_status'].replace('_', ' ')}"))
        items.append(ListItem(label="Evidence check", text=f["evidence_validation"].replace("_", " "),
                              tone="failed" if f["evidence_validation"] == "failed" else "neutral"))
        if f["finding_id"] in reasons:
            items.append(ListItem(label="Citation problem", text=reasons[f["finding_id"]], tone="failed"))
        blocks.append(TextBlock(text=f"**{f['rule_id']}** on {_on(f, names)} · {f['severity']}\n\n{f['message']}"))
        blocks.append(ListBlock(title="Why", items=items))
    return Reply(blocks=blocks, data={"version": rec["version"], "findings": matches[:3]})


@intent("list_findings", group="case_query",
        description="List or filter the findings of a case (by severity, rule, document, document "
                    "type, category or review status).",
        examples=("show the high severity findings in case CASE-12",
                  "which findings on invoices need review?"),
        patterns={r"\bfindings?\b": 1.5, r"\b(issues?|problems?|violations?|flags?|exceptions?)\b": 1.0,
                  r"\b(show|list|which|what are|give me|any)\b": 0.5},
        signals={"severities": 1.0, "categories": 1.0, "review_statuses": 1.0,
                 "case_ids": 0.5, "doc_ids": 0.5, "doc_types": 0.3}, needs=("saved_case",),
        follow_ups=("What evidence is missing?", "What changed since the last audit?"))
def list_findings(turn: Turn) -> Reply:
    version = turn.entities.versions[0] if turn.entities.versions else None
    rec = turn.record(version)
    if rec is None:
        return Reply(f"Case {turn.case_id} has no version {version}.")
    matches = _filter(rec["findings"], turn.entities, rec)
    e = turn.entities
    filters = {"severities": e.severities, "rule_ids": e.rule_ids, "doc_ids": e.doc_ids,
               "doc_types": e.doc_types, "categories": e.categories,
               "review_statuses": e.review_statuses}
    head = f"Case {turn.case_id}, version {rec['version']}: {len(matches)} matching finding(s)."
    blocks = [TextBlock(text=head)]
    if matches:
        blocks.append(_findings_block("", matches))
    return Reply(blocks=blocks, data={"version": rec["version"], "findings": matches, "filters": filters})


@intent("evidence_gaps", group="case_query",
        description="What evidence is missing, rejected or unverified in a case, and what to supply.",
        examples=("what evidence is missing for case CASE-3?", "which documents were rejected?"),
        patterns={r"\b(missing|gaps?|rejected|incomplete|unverified|lacking|insufficient)\b": 2.0,
                  r"\bevidence\b": 0.5, r"\bwhat (else|more) (is )?(needed|required)\b": 2.0},
        signals={"case_ids": 0.5}, needs=("saved_case",),
        follow_ups=("Show the findings that need review", "Show the audit history"))
def evidence_gaps(turn: Turn) -> Reply:
    rec = turn.record()
    names = _names(rec)
    blocks = [TextBlock(text=f"Evidence gaps in case {turn.case_id}, version {rec['version']}.")]
    if rec["rejected_records"]:
        blocks.append(ListBlock(title="Left out of the rule checks", items=[
            ListItem(label=names.get(d, d), text="its data could not be used", tone="failed")
            for d in rec["rejected_records"]]))
    failed = rec.get("rejected_findings", [])[:MAX]
    if failed:
        blocks.append(ListBlock(title="Citations that failed validation", items=[
            ListItem(label=r["finding"]["rule_id"], text=r["reason"], tone="failed") for r in failed]))
    gaps = [f for f in rec["findings"] if f["rule_id"].startswith("REV-")]
    if gaps:
        blocks.append(_findings_block("Review items", gaps))
    if len(blocks) == 1:
        blocks = [TextBlock(text=f"No evidence gaps recorded for case {turn.case_id}.")]
    return Reply(blocks=blocks, data={"version": rec["version"], "rejected_records": rec["rejected_records"],
                                      "rejected_findings": rec.get("rejected_findings", []),
                                      "review_items": gaps, "findings": gaps})


@intent("compare_versions", group="case_query",
        description="Compare two versions of a case: new, resolved and changed findings.",
        examples=("what changed since the last audit of case C-1?", "compare version 1 and 2 of CASE-9"),
        patterns={r"\b(compare|comparison|diff(erence)?|changed?|versus|vs\.?)\b": 2.0,
                  r"\bsince (the )?(last|previous)\b": 1.5},
        signals={"versions": 1.0}, needs=("saved_case",),
        follow_ups=("Show the high severity findings", "Show the audit history"))
def compare_versions(turn: Turn) -> Reply:
    latest = turn.record()
    vs = sorted(turn.entities.versions)
    new_v = vs[-1] if len(vs) >= 2 else latest["version"]
    old_v = vs[0] if vs and vs[0] != new_v else new_v - 1
    old, new = turn.record(old_v) if old_v >= 1 else None, turn.record(new_v)
    if old is None or new is None:
        return Reply(f"Case {turn.case_id} needs two saved versions to compare "
                     f"(latest is {latest['version']}).")
    a = {f["finding_id"]: f for f in old["findings"]}
    b = {f["finding_id"]: f for f in new["findings"]}
    added = [b[k] for k in b if k not in a]
    resolved = [a[k] for k in a if k not in b]
    changed = [b[k] for k in b if k in a and any(
        a[k][x] != b[k][x] for x in ("severity", "message", "review_status", "evidence_validation"))]
    blocks = [TextBlock(text=f"Case {turn.case_id}: version {old_v} → {new_v}. {len(added)} new, "
                             f"{len(resolved)} resolved, {len(changed)} changed.")]
    for title, items in (("New", added), ("Resolved", resolved), ("Changed", changed)):
        if items:
            blocks.append(_findings_block(title, items))
    return Reply(blocks=blocks, data={"from": old_v, "to": new_v, "findings": added + changed,
                                      "new": added, "resolved": resolved, "changed": changed})


@intent("list_versions", group="case_query",
        description="The audit history of a case: every saved version.",
        examples=("show the audit history of case CASE-2", "how many times was C-1 audited?"),
        patterns={r"\b(history|versions|previous runs|past audits|audit trail|how many times)\b": 2.0},
        signals={"case_ids": 0.3}, needs=("saved_case",),
        follow_ups=("What changed since the last audit?", "Summarise this case"))
def list_versions(turn: Turn) -> Reply:
    rows = turn.store.versions(turn.case_id)
    table = TableBlock(columns=["Version", "Saved", "Verdict", "Score", "Findings", "Documents"], rows=[
        [f"v{r['version']}", r["created_at"][:16].replace("T", " "),
         (r.get("verdict") or r["status"]).replace("_", " "),
         "" if r.get("score") is None else str(r["score"]), str(r["findings"]), str(r["docs"])]
        for r in rows])
    return Reply(blocks=[TextBlock(text=f"Case {turn.case_id} has {len(rows)} saved version(s)."), table],
                 data={"versions": rows})


@intent("case_status", group="case_query",
        description="Summary of a case's latest audit result.",
        examples=("what is the status of case CASE-12?", "summarise the audit of ACME-1"),
        patterns={r"\b(status|summary|summari[sz]e|overview|results?|outcome|auditable|"
                  r"how (is|did|was))\b": 1.5,
                  r"\b(latest|current)\b": 0.5},
        signals={"case_ids": 1.0}, needs=("saved_case",),
        follow_ups=("Show the high severity findings", "What evidence is missing?", "What changed since the last audit?"))
def case_status(turn: Turn) -> Reply:
    rec = turn.record()
    names = _names(rec)
    failed = sum(f["evidence_validation"] == "failed" for f in rec["findings"])
    facts = [
        ListItem(label="Documents", text=", ".join(names.values()) or "none"),
        ListItem(label="Findings", text=_counts(rec["findings"])),
        ListItem(label="Rejected documents", text=str(len(rec["rejected_records"]))),
        ListItem(label="Citations failed", text=str(failed), tone="failed" if failed else "neutral"),
        ListItem(label="Rules from", text=f"the {rec['kg_source'].replace('_', ' ')} knowledge graph"),
    ]
    blocks = [VerdictBlock(case_id=turn.case_id, version=rec["version"],
                           verdict=rec.get("verdict") or rec["status"], score=rec.get("score"),
                           summary=rec.get("summary") or ""),
              ListBlock(items=facts)]
    top = [f for f in rec["findings"] if f["severity"] == "high"]
    if top:
        blocks.append(_findings_block("High severity", top))
    return Reply(blocks=blocks, data={"version": rec["version"], "status": rec["status"],
                                      "findings": rec["findings"]})


@intent("search_cases", group="case_query",
        description="Find audited cases across the system matching a condition (status, severity, "
                    "rule, category).",
        examples=("which cases have possible fraud findings?", "list all cases that are not auditable"),
        patterns={r"\b(which|what|all|any|list) (the )?cases\b": 2.5, r"\bcases\b": 1.0,
                  r"\b(across|every|each) cases?\b": 1.5},
        signals={"severities": 0.5, "categories": 0.5, "rule_ids": 0.5, "case_ids": -2.0},
        follow_ups=("Which cases are not auditable?", "Which cases have high severity findings?"))
def search_cases(turn: Turn) -> Reply:
    want_not_auditable = "not auditable" in turn.query.text.lower()
    filters = any((turn.entities.severities, turn.entities.categories, turn.entities.rule_ids,
                   turn.entities.review_statuses, turn.entities.doc_types))
    hits = []
    for rec in turn.store.latest_all():
        if want_not_auditable and rec["status"] != "not_auditable":
            continue
        matches = _filter(rec["findings"], turn.entities, rec) if filters else rec["findings"]
        if filters and not matches:
            continue
        hits.append({"case_id": rec["case_id"], "version": rec["version"], "status": rec["status"],
                     "verdict": rec.get("verdict"), "matching_findings": len(matches)})
    if not hits:
        return Reply("No saved case matches.", {"cases": hits})
    table = TableBlock(columns=["Case", "Version", "Verdict", "Matching findings"], rows=[
        [h["case_id"], f"v{h['version']}", (h["verdict"] or h["status"]).replace("_", " "),
         str(h["matching_findings"])] for h in hits[:MAX]])
    blocks = [TextBlock(text=f"{len(hits)} case(s) match."), table]
    if len(hits) > MAX:
        blocks.append(TextBlock(text=f"…and {len(hits) - MAX} more."))
    return Reply(blocks=blocks, data={"cases": hits})


# --- rules and standards (rule_query) --------------------------------------------------

@intent("rule_explain", group="rule_query",
        description="Explain what a rule checks and which standard it comes from.",
        examples=("explain CHK-004", "what is POL-07 based on?"),
        # "mean"/"meaning" belong to standard_search; a named rule id is what makes this intent
        patterns={r"\b(explain|basis|based on|source)\b": 1.5, r"\bwhat (does|is)\b": 0.5},
        signals={"rule_ids": 2.0, "case_ids": -1.5}, needs=("rule",),
        follow_ups=("Which rules apply to invoices?", "What does LKAS 2 say about inventories?"))
def rule_explain(turn: Turn) -> Reply:
    blocks, data = [], {}
    for rule_id in turn.entities.rule_ids:
        if rule_id.startswith("REV-"):
            blocks.append(TextBlock(text=f"**{rule_id}** is a Component-03 review item, not a KG rule: "
                                         f"a person must check it, and it never counts as a violation."))
            continue
        exp = turn.kg.explain_rule(rule_id)
        rule, doc_types = _rule_facts(turn.kg, rule_id)
        data[rule_id] = exp.model_dump() if exp else None
        if exp is None and rule is None:
            blocks.append(TextBlock(text=f"**{rule_id}** was not found in the knowledge graph."))
            continue
        name = getattr(rule, "name", "") or ""
        items = []
        if rule is not None and hasattr(rule, "expression"):
            items.append(ListItem(label="Checks", text=f"`{rule.expression}`"))
            items.append(ListItem(label="Severity", text=rule.severity, tone=rule.severity))
        elif rule is not None:
            need = rules_mod.required_approvals(rule)
            if rule.limit is not None:
                items.append(ListItem(label="Limit", text=f"Rs {fmt(float(rule.limit))}"))
            if need:
                items.append(ListItem(label="Approvals needed", text=str(need)))
        if doc_types:
            items.append(ListItem(label="Applies to", text=", ".join(_doc_words(t) for t in doc_types)))
        if exp is not None:
            cites = [c.ref for c in exp.citations if c.ref]
            if cites:
                items.append(ListItem(label="Based on", text=", ".join(cites)))
            if exp.assertions:
                items.append(ListItem(label="Tests", text=", ".join(exp.assertions)))
            if exp.risks:
                items.append(ListItem(label="Addresses", text=", ".join(exp.risks)))
        about = (exp.explanation if exp else "") or getattr(rule, "text", "")
        about = about.removeprefix(rule_id).strip(" :")  # the KG repeats the id at the start
        title = " ".join(p for p in (rule_id, name) if p)
        blocks.append(TextBlock(text=f"**{title}**" + (f"\n\n{about}" if about else "")))
        if items:
            blocks.append(ListBlock(items=items))
    return Reply(blocks=blocks, data={"explanations": data, "kg_source": turn.kg.source})


@intent("rule_lookup", group="rule_query",
        description="Which rules and limits apply to a document type; can compare a stated amount "
                    "with the policy limits.",
        examples=("what is the dual approval limit for invoices?", "which checks apply to a balance sheet?"),
        patterns={r"\b(rules?|limits?|thresholds?|polic(y|ies)|requirements?|controls?|approvals?)\b": 1.5,
                  r"\b(apply|applies|applicable|checks? (for|on))\b": 1.0},
        signals={"doc_types": 1.0, "case_ids": -1.0}, needs=("doc_type",),
        follow_ups=("Explain POL-07", "Which checks apply to a balance sheet?"))
def rule_lookup(turn: Turn) -> Reply:
    blocks, data = [], {}
    for doc_type in turn.entities.doc_types:
        checks, policy = turn.kg.get_check_rules(doc_type), turn.kg.get_rules(doc_type)
        data[doc_type] = {"check_rules": [r.model_dump() for r in checks],
                          "policy_rules": [r.model_dump() for r in policy]}
        items = [_rule_item(r) for r in [*checks, *policy]]
        if not items:
            blocks.append(TextBlock(text=f"The knowledge graph has no rules for a {_doc_words(doc_type)} "
                                         f"yet, so only the data checks run on it."))
            continue
        noun = _doc_words(doc_type)
        article = "an" if noun[0] in "aeiou" else "a"
        blocks.append(ListBlock(title=f"{len(items)} rule(s) apply to {article} {noun}", items=items))
        compared = []
        for amount in turn.entities.amounts:
            for r in policy:
                if r.limit is not None:
                    side = "above" if amount.value > r.limit else "within"
                    compared.append(ListItem(label=amount.text, text=f"is {side} the {r.rule_id} limit "
                                                                    f"Rs {fmt(float(r.limit))}",
                                             tone="review" if side == "above" else "passed"))
        if compared:
            blocks.append(ListBlock(title="Your amount", items=compared))
    return Reply(blocks=blocks, data={"rules": data, "kg_source": turn.kg.source})


_DEFINE = re.compile(r"\b(?:define|definition of|meaning of|what (?:is|are) meant by|what does)\s+"
                     r"(?:the\s+)?(?:term\s+)?['\"]?([A-Za-z][A-Za-z '\-]{1,60}?)['\"]?"
                     r"(?:\s+mean)?\s*\??\s*$", re.IGNORECASE)


def _section_reply(turn: Turn) -> Reply | None:
    items, data = [], []
    for ref in turn.entities.sections[:3]:
        sec = turn.kg.get_section(ref)
        if sec is None:
            items.append(ListItem(label=ref, text="not found in the knowledge graph"))
            continue
        data.append(sec.model_dump())
        details = [f"Caution: {sec.standard} is {sec.standard_status}."] if sec.standard_status != "active" else []
        items.append(ListItem(label=f"{sec.id} · {sec.heading}" if sec.heading else sec.id,
                              text=f"{sec.text} ({sec.standard_title or sec.standard})", details=details))
    if not items:
        return None
    return Reply(blocks=[ListBlock(items=items)], data={"sections": data, "kg_source": turn.kg.source})


def _definition_reply(turn: Turn) -> Reply | None:
    m = _DEFINE.search(turn.query.text.strip())
    if not m:
        return None
    term = m.group(1).strip()
    defs = turn.kg.get_definitions(term)
    if defs:
        items = [ListItem(label=d.term, text=d.text,
                          details=[f"Defined in {', '.join(d.defined_in)}"] if d.defined_in else [])
                 for d in defs[:3]]
        return Reply(blocks=[ListBlock(items=items)], data={"definitions": [d.model_dump() for d in defs],
                                                            "kg_source": turn.kg.source})
    item = turn.kg.get_line_item(term.lower().replace(" ", "_").replace("-", "_"))
    if item is None:
        return None
    details = []
    if item.statements:
        details.append(f"Shown in: {', '.join(item.statements)}")
    if item.aliases:
        details.append(f"Also written as: {', '.join(item.aliases)}")
    if item.equations:
        details.append(f"Used in: {'; '.join(item.equations)}")
    return Reply(blocks=[ListBlock(items=[ListItem(label=item.name or item.code, text="a line item in the "
                                                   "financial statements", details=details)])],
                 data={"line_item": item.model_dump(), "kg_source": turn.kg.source})


@intent("standard_search", group="rule_query",
        description="Look up what an accounting or auditing standard (LKAS, SLFRS, SLAuS) says: a "
                    "paragraph, a defined term, or a topic.",
        examples=("what does LKAS 2 say about inventories?", "define net realisable value"),
        patterns={r"\b(what does|says?|say about|according to|standards?|paragraph|para|definition|define|"
                  r"meaning of|requirement|mean)\b": 1.5},
        signals={"standards": 2.0, "sections": 1.0},
        follow_ups=("Which rules apply to a balance sheet?",))
def standard_search(turn: Turn) -> Reply:
    """An exact paragraph first ("LKAS 2:9"), then a defined term or line item
    ("define net realisable value"), else a search of the standards."""
    exact = _section_reply(turn) or _definition_reply(turn)
    if exact is not None:
        return exact
    hits = turn.kg.search(turn.query.text)
    if not hits:
        return Reply("Nothing matched in the standards. Name a standard (e.g. LKAS 2), a paragraph "
                     "(e.g. LKAS 2:9) or a topic (e.g. inventories).",
                     {"search": [], "kg_source": turn.kg.source})
    items = [ListItem(label=h.get("section") or h.get("standard") or "Source", text=h.get("text", ""))
             for h in hits[:3]]
    return Reply(blocks=[ListBlock(title="From the standards", items=items)],
                 data={"search": hits, "kg_source": turn.kg.source})


@intent("generate_report", group="case_query",
        description="Make the PDF audit report of an audited case (by Component-04).",
        examples=("generate the report", "download the audit report for case ACME-1 as a PDF"),
        patterns={r"\b(generate|create|make|build|download|get|prepare|export|give)\b.*\b(report|pdf)\b": 3.0,
                  r"\breport\b": 1.0, r"\bpdf\b": 1.5},
        needs=("saved_case",),
        follow_ups=("Show the high severity findings", "Summarise this case"))
def generate_report(turn: Turn) -> Reply:
    version = turn.entities.versions[0] if turn.entities.versions else None
    rec = turn.record(version) if version else turn.record()
    if rec is None:
        return Reply(f"Case {turn.case_id} has no version {version}.")
    try:
        out = c4_report.request_report(turn.case_id, rec["version"])
    except c4_report.C4Unavailable as exc:
        return Reply(f"I couldn't make the report: {exc}. Start Component-04 and ask again.",
                     {"report_error": str(exc)})
    data = {"report_url": out["report_url"], "audit_id": c4_report.audit_id(turn.case_id, rec["version"]),
            "version": rec["version"]}
    if not out.get("report_url"):
        return Reply(f"Component-04 made the report for case {turn.case_id} version {rec['version']}, "
                     f"but sent no link to it.", data)
    return Reply(blocks=[TextBlock(text=f"The audit report for case {turn.case_id} (version "
                                        f"{rec['version']}) is ready."),
                         LinkBlock(label="Open the PDF report", url=out["report_url"])], data=data)


# --- conversation ------------------------------------------------------------------
# Greetings and thanks match only when they are the whole message, so
# "hi, list the findings" still goes to list_findings.
CONVERSATION = ("greeting", "thanks", "out_of_scope", "help")


def _case_hint(turn: Turn) -> str:
    rec = turn.record() if turn.case_id else None
    if rec is None:
        return "Pick a case in the Library, or ask me about a rule or a standard."
    rule = [f for f in rec.get("findings", []) if not str(f.get("rule_id", "")).startswith("REV-")]
    return (f"We are on case {turn.case_id} (version {rec['version']}, {len(rule)} rule finding(s)). "
            f"Ask me to summarise it or explain a finding.")


@intent("greeting", group="other",
        description="The user greets the Copilot (hi, hello, good morning).",
        examples=("hey", "good morning"),
        patterns={r"^\W*(hi+|hey+|hello+|hiya|ayubowan|good\s+(morning|afternoon|evening))"
                  r"(\s+(there|team|copilot|nomos))?\W*$": 3.0},
        follow_ups=("Summarise this case", "What can you do?"))
def greeting(turn: Turn) -> Reply:
    return Reply(f"Hello! I'm the NOMOS Audit Copilot. {_case_hint(turn)}")


@intent("thanks", group="other",
        description="The user says thanks or acknowledges an answer (thanks, ok, great).",
        examples=("thanks", "ok great"),
        patterns={r"^(?=.*[a-z])\W*((ok(ay)?|great|nice|cool|perfect)[\s,!.]*)*"
                  r"(thanks|thank\s+you|thx|ty|cheers)?(\s+(a\s+lot|so\s+much|very\s+much))?\W*$": 3.0},
        follow_ups=("Summarise this case", "What can you do?"))
def thanks(turn: Turn) -> Reply:
    return Reply("You're welcome! Anything else on this audit?")


@intent("out_of_scope", group="other",
        description="The request is not about audits, findings, rules or accounting standards "
                    "(weather, jokes, general knowledge).",
        examples=("what's the weather today?", "tell me a joke"),
        follow_ups=("What can you do?", "Summarise this case"))
def out_of_scope(turn: Turn) -> Reply:
    return Reply("I can't help with that. I answer questions about this audit: its findings, the "
                 "rules behind them and the accounting standards. Ask \"what can you do?\" for examples.")


@intent("help", group="other",
        description="The user asks what the Copilot can do.",
        examples=("help", "what can you do?"),
        patterns={r"\b(help|what can you do|how do i|commands|options)\b": 2.0},
        follow_ups=("Summarise this case", "Which rules apply to invoices?", "I paid Rs 150,000 cash but booked it on credit, is that ok?"))
def help_intent(turn: Turn) -> Reply:
    items = [ListItem(label=s.description.rstrip("."), text=f"e.g. “{s.examples[0]}”")
             for s in REGISTRY.values() if s.name not in CONVERSATION]
    return Reply(blocks=[ListBlock(title="I can help with", items=items)])


