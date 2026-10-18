"""Copilot intent handlers. One decorated function per intent; registration
order is the tie-break order of the rules classifier (more specific first).

Every reply is built from stored results or KG data in code. The LLM never
writes a reply and never decides a verdict.
"""
from collections import Counter
from dataclasses import dataclass, field

from app import config
from app.schemas.copilot import CopilotQuery
from app.services import intake, orchestrator
from app.services.copilot import whatif
from app.services.copilot.entities import Entities
from app.services.copilot.registry import REGISTRY, intent
from app.services.events import EventPublisher
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
    text: str
    data: dict | None = None


# --- formatting --------------------------------------------------------------

def _is_review(f: dict) -> bool:
    return f["rule_id"].startswith("REV-") or f["review_status"] == "needs_more_evidence"


def _line(f: dict) -> str:
    flag = " [citation failed]" if f.get("citation_unverified") else ""
    return f"- {f['rule_id']} ({f['severity']}, {f['review_status']}){flag}: {f['message']}"


def _bullets(findings: list[dict]) -> str:
    more = f"\n...and {len(findings) - MAX} more." if len(findings) > MAX else ""
    return "\n".join(_line(f) for f in findings[:MAX]) + more


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


def _run_summary(result) -> str:
    findings = [f.model_dump() for f in result.findings]
    return (f"Case {result.case_id} version {result.version} saved ({result.status}): "
            f"{_counts(findings)}.\n{_bullets(findings)}")


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
    result = orchestrator.run_case(case, turn.kg, store=MemoryStore(),
                                   publisher=EventPublisher(silent_reason="what-if check"), narrate=False)
    findings = [f.model_dump() for f in result.findings]
    rule_findings = [f for f in findings if not f["rule_id"].startswith("REV-")]
    shown = ", ".join(f"{k}={fmt(v) if isinstance(v, float) else v}" for k, v in read["fields"].items())
    head = (f"What-if check on a {read['doc_type']} (not saved). I read: {shown}. "
            f"Correct me if a value is wrong.")
    body = (_bullets(rule_findings) if rule_findings
            else "No audit rule failed for these values.")
    return Reply(f"{head}\n{body}", {"read": read, "findings": rule_findings,
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
    return Reply(_run_summary(result), result.model_dump())


@intent("fresh_audit", group="fresh_audit",
        description="Run a new audit on the documents attached to the request.",
        examples=("audit these documents", "run a fresh audit on this year's books"),
        patterns={r"\b(fresh|new) audit\b": 2.5, r"\bfrom scratch\b": 2.0,
                  r"\b(audit|check|review|analy[sz]e|examine|verify)\b": 1.0,
                  r"\b(these|this|attached) (documents?|docs|files|books|records)\b": 1.5},
        signals={"docs": 2.0, "docs_for_audited_case": -1.5}, needs=("case", "docs"),
        follow_ups=("Show the high severity findings", "What evidence is missing?", "Summarise this case"))
def fresh_audit(turn: Turn) -> Reply:
    case = intake.normalize_case({"case_id": turn.case_id, "docs": turn.query.docs})
    result = orchestrator.run_case(case, turn.kg, store=turn.store)
    return Reply(_run_summary(result), result.model_dump())


@intent("rerun_audit", group="fresh_audit",
        description="Run an already audited case again on its latest documents (e.g. after the "
                    "rules changed), saving a new version.",
        examples=("re-run case CASE-7", "audit case ACME-1 again with the new rules"),
        patterns={r"\bre-?run\b": 2.5, r"\b(again|once more)\b": 1.5, r"\bre-?audit\b": 2.0},
        signals={"case_ids": 0.5, "docs": -1.0}, needs=("saved_case",),
        follow_ups=("What changed since the last audit?", "Show the high severity findings"))
def rerun_audit(turn: Turn) -> Reply:
    case = intake.normalize_case(turn.record()["case"])
    result = orchestrator.run_case(case, turn.kg, store=turn.store)
    return Reply(_run_summary(result), result.model_dump())


# --- questions about saved audits (case_query) ---------------------------------------

@intent("explain_finding", group="case_query",
        description="Explain why a specific finding was raised in a case: the rule, the values "
                    "checked, the evidence and its validation.",
        examples=("why did CHK-004 fire on case ABC-1?", "explain the POL-07 finding on INV-9"),
        patterns={r"\bwhy\b": 1.5, r"\b(fired|flagged|raised|triggered|failed)\b": 1.5,
                  r"\breason(ing)?\b": 1.0, r"\bexplain\b": 0.5, r"\bfinding\b": 1.0},
        signals={"rule_ids": 1.0, "doc_ids": 1.0, "case_ids": 1.0}, needs=("saved_case",),
        follow_ups=("Show the findings that need review", "What evidence is missing?"))
def explain_finding(turn: Turn) -> Reply:
    rec = turn.record()
    matches = _filter(rec["findings"], turn.entities, rec)
    if not (turn.entities.rule_ids or turn.entities.doc_ids) and len(rec["findings"]) > 1:
        ids = ", ".join(sorted({f["rule_id"] for f in rec["findings"]}))
        return Reply(f"Which finding? Case {turn.case_id} has: {ids}. Name a rule id or document.")
    if not matches:
        return Reply(f"No finding in case {turn.case_id} (version {rec['version']}) matches that.")
    reasons = {r["finding"]["finding_id"]: r["reason"] for r in rec.get("rejected_findings", [])}
    parts = []
    for f in matches[:3]:
        lines = [f"{f['rule_id']} on {', '.join(f['evidence_ids']) or 'the case'}: {f['message']}",
                 *(f"  - {step}" for step in f["reasoning_chain"]),
                 (f"  - confidence {f['confidence']:.2f}, review status {f['review_status']}, "
                 f"evidence {f['evidence_validation']}")]
        if f["finding_id"] in reasons:
            lines.append(f"  - citation problem: {reasons[f['finding_id']]}")
        parts.append("\n".join(lines))
    return Reply("\n\n".join(parts), {"version": rec["version"], "findings": matches[:3]})


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
    head = f"Case {turn.case_id} version {rec['version']}: {len(matches)} matching finding(s)."
    return Reply(f"{head}\n{_bullets(matches)}" if matches else head,
                 {"version": rec["version"], "findings": matches})


@intent("evidence_gaps", group="case_query",
        description="What evidence is missing, rejected or unverified in a case, and what to supply.",
        examples=("what evidence is missing for case CASE-3?", "which documents were rejected?"),
        patterns={r"\b(missing|gaps?|rejected|incomplete|unverified|lacking|insufficient)\b": 2.0,
                  r"\bevidence\b": 0.5, r"\bwhat (else|more) (is )?(needed|required)\b": 2.0},
        signals={"case_ids": 0.5}, needs=("saved_case",),
        follow_ups=("Show the findings that need review", "Show the audit history"))
def evidence_gaps(turn: Turn) -> Reply:
    rec = turn.record()
    lines = []
    if rec["rejected_records"]:
        lines.append(f"Rejected documents (not checked): {', '.join(rec['rejected_records'])}.")
    for r in rec.get("rejected_findings", [])[:MAX]:
        lines.append(f"- {r['finding']['rule_id']} citation failed: {r['reason']}")
    gaps = [f for f in rec["findings"] if f["rule_id"].startswith("REV-")]
    if gaps:
        lines.append("Review items:\n" + _bullets(gaps))
    text = "\n".join(lines) or f"No evidence gaps recorded for case {turn.case_id}."
    return Reply(f"Case {turn.case_id} version {rec['version']}:\n{text}",
                 {"version": rec["version"], "rejected_records": rec["rejected_records"],
                  "rejected_findings": rec.get("rejected_findings", []), "review_items": gaps,
                  "findings": gaps})


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
    parts = [(f"Case {turn.case_id}: version {old_v} -> {new_v}. "
             f"{len(added)} new, {len(resolved)} resolved, {len(changed)} changed.")]
    for title, items in (("New", added), ("Resolved", resolved), ("Changed", changed)):
        if items:
            parts.append(f"{title}:\n{_bullets(items)}")
    return Reply("\n".join(parts), {"from": old_v, "to": new_v, "findings": added + changed,
                                    "new": added, "resolved": resolved, "changed": changed})


@intent("list_versions", group="case_query",
        description="The audit history of a case: every saved version.",
        examples=("show the audit history of case CASE-2", "how many times was C-1 audited?"),
        patterns={r"\b(history|versions|previous runs|past audits|audit trail|how many times)\b": 2.0},
        signals={"case_ids": 0.3}, needs=("saved_case",),
        follow_ups=("What changed since the last audit?", "Summarise this case"))
def list_versions(turn: Turn) -> Reply:
    rows = turn.store.versions(turn.case_id)
    lines = [f"- v{r['version']} {r['created_at'][:19]} {r['status']}: {r['findings']} finding(s), "
             f"{r['docs']} document(s)" for r in rows]
    return Reply(f"Case {turn.case_id} has {len(rows)} saved version(s):\n" + "\n".join(lines),
                 {"versions": rows})


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
    failed = sum(f["evidence_validation"] == "failed" for f in rec["findings"])
    text = (f"Case {turn.case_id} version {rec['version']} ({rec['created_at'][:19]}): "
            f"{rec['status']}. {_counts(rec['findings'])}. "
            f"{len(rec['rejected_records'])} document(s) rejected, {failed} citation(s) failed. "
            f"Rules from the {rec['kg_source']} knowledge graph.")
    top = [f for f in rec["findings"] if f["severity"] == "high"]
    return Reply(text + (f"\nHigh severity:\n{_bullets(top)}" if top else ""),
                 {"version": rec["version"], "status": rec["status"], "findings": rec["findings"]})


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
        hits.append({"case_id": rec["case_id"], "version": rec["version"],
                     "status": rec["status"], "matching_findings": len(matches)})
    lines = [f"- {h['case_id']} v{h['version']} ({h['status']}): {h['matching_findings']} "
             f"matching finding(s)" for h in hits[:MAX]]
    return Reply(f"{len(hits)} case(s) match.\n" + "\n".join(lines) if hits
                 else "No saved case matches.", {"cases": hits})


# --- rules and standards (rule_query) --------------------------------------------------

@intent("rule_explain", group="rule_query",
        description="Explain what a rule checks and which standard it comes from.",
        examples=("explain CHK-004", "what is POL-07 based on?"),
        patterns={r"\b(explain|meaning|mean|basis|based on|source)\b": 1.5, r"\bwhat (does|is)\b": 0.5},
        signals={"rule_ids": 2.0, "case_ids": -1.5}, needs=("rule",),
        follow_ups=("Which rules apply to invoices?", "What does LKAS 2 say about inventories?"))
def rule_explain(turn: Turn) -> Reply:
    lines, data = [], {}
    for rule_id in turn.entities.rule_ids:
        if rule_id.startswith("REV-"):
            lines.append(f"{rule_id} is a Component-03 review item (not a KG rule): a human "
                         f"must check it; it is never counted as a violation.")
            continue
        exp = turn.kg.explain_rule(rule_id)
        data[rule_id] = exp.model_dump() if exp else None
        if exp is None:
            lines.append(f"{rule_id}: not found in the knowledge graph.")
            continue
        cites = ", ".join(c.ref for c in exp.citations if c.ref)
        lines.append(f"{rule_id}: {exp.explanation}" + (f" (sources: {cites})" if cites else ""))
    return Reply("\n".join(lines), {"explanations": data, "kg_source": turn.kg.source})


@intent("rule_lookup", group="rule_query",
        description="Which rules and limits apply to a document type; can compare a stated amount "
                    "with the policy limits.",
        examples=("what is the dual approval limit for invoices?", "which checks apply to a balance sheet?"),
        patterns={r"\b(rules?|limits?|thresholds?|polic(y|ies)|requirements?|controls?|approvals?)\b": 1.5,
                  r"\b(apply|applies|applicable|checks? (for|on))\b": 1.0},
        signals={"doc_types": 1.0, "case_ids": -1.0}, needs=("doc_type",),
        follow_ups=("Explain POL-07", "Which checks apply to a balance sheet?"))
def rule_lookup(turn: Turn) -> Reply:
    lines, data = [], {}
    for doc_type in turn.entities.doc_types:
        checks, policy = turn.kg.get_check_rules(doc_type), turn.kg.get_rules(doc_type)
        data[doc_type] = {"check_rules": [r.model_dump() for r in checks],
                          "policy_rules": [r.model_dump() for r in policy]}
        names = [f"{r.rule_id} {r.name}" for r in checks]
        names += [f"{r.rule_id} {r.text}" for r in policy]
        lines.append(f"Rules for {doc_type}: " + ("; ".join(names) if names else "none in the KG."))
        for amount in turn.entities.amounts:
            for r in policy:
                if r.limit is not None:
                    side = "above" if amount.value > r.limit else "within"
                    lines.append(f"  {amount.text} is {side} the {r.rule_id} limit {fmt(float(r.limit))}.")
    return Reply("\n".join(lines), {"rules": data, "kg_source": turn.kg.source})


@intent("standard_search", group="rule_query",
        description="Look up what an accounting or auditing standard (LKAS, SLFRS, SLAuS) says "
                    "about a topic.",
        examples=("what does LKAS 2 say about inventories?", "define materiality"),
        patterns={r"\b(what does|says?|say about|according to|standards?|paragraph|definition|define|"
                  r"meaning of|requirement)\b": 1.5},
        signals={"standards": 2.0},
        follow_ups=("Which rules apply to a balance sheet?",))
def standard_search(turn: Turn) -> Reply:
    hits = turn.kg.search(turn.query.text)
    if not hits:
        return Reply("Nothing matched in the standards. Name a standard (e.g. LKAS 2) or a topic "
                     "(e.g. inventories).", {"search": [], "kg_source": turn.kg.source})
    lines = [f"- {h.get('section') or h.get('standard') or 'source'}: {h.get('text', '')}"
             for h in hits[:3]]
    return Reply("\n".join(lines), {"search": hits, "kg_source": turn.kg.source})


@intent("help", group="other",
        description="The user asks what the Copilot can do, or the request fits nothing else.",
        examples=("help", "what can you do?"),
        patterns={r"\b(help|what can you do|how do i|commands|options)\b": 2.0},
        follow_ups=("Summarise this case", "Which rules apply to invoices?", "I paid Rs 150,000 cash but booked it on credit, is that ok?"))
def help_intent(turn: Turn) -> Reply:
    lines = [f"- {s.description} e.g. \"{s.examples[0]}\""
             for s in REGISTRY.values() if s.name != "help"]
    return Reply("I can:\n" + "\n".join(lines))
