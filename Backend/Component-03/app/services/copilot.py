"""Audit Copilot: route a natural-language request to one of three intents and
carry it out. Routing is deterministic (word patterns + what the request
carries), so it is repeatable and measurable against a labelled query set.

- rule_query      rules for a document type, one rule's KG basis, or a standards search
- evidence_append add documents to the latest saved version of a case and re-run
- fresh_audit     run a new audit on the documents sent
Replies are built from data; the LLM never writes them.
"""
import re

from app import config
from app.schemas.copilot import CopilotQuery, CopilotResponse, Intent
from app.services import intake, orchestrator
from app.services.kg_client import KGClient, KGError, default_kg
from app.services.store import ResultStore, default_store

_FRESH = re.compile(r"\b(fresh|new audit|start over|from scratch|re-?audit)\b", re.IGNORECASE)
_APPEND = re.compile(r"\b(add(ing)?|append|attach|upload|include|more evidence|another "
                     r"(document|invoice|receipt|bill)|new (bill|evidence|document|invoice|receipt))\b", re.IGNORECASE)
_RULE = re.compile(r"\b(rules?|limits?|polic(y|ies)|thresholds?|standards?|clauses?|explain|why|"
                   r"lkas|slfrs|slaus|paragraph|requirement|chk-\d+|pol-\d+)\b", re.IGNORECASE)
_NO_MATCH = ("Nothing matched. Name a document type (e.g. balance sheet), a rule id "
             "(e.g. CHK-001) or a standard (e.g. LKAS 2).")
_RULE_ID = re.compile(r"\b(CHK|POL)-\d+\b", re.IGNORECASE)


def classify(text: str, has_docs: bool = False) -> Intent:
    if _FRESH.search(text):
        return "fresh_audit"
    if _APPEND.search(text):
        return "evidence_append"
    if _RULE.search(text):
        return "rule_query"
    return "fresh_audit" if has_docs else "rule_query"


def _doc_types_in(text: str) -> list[str]:
    low = text.lower()
    return [t for t in sorted(config.ALLOWED_DOC_TYPES)
            if t != "unknown" and (t in low or t.replace("_", " ") in low)]


def _rule_query(text: str, kg: KGClient) -> CopilotResponse:
    lines: list[str] = []
    data: dict = {}
    for rule_id in dict.fromkeys(m.group(0).upper() for m in _RULE_ID.finditer(text)):
        exp = kg.explain_rule(rule_id)
        data.setdefault("explanations", {})[rule_id] = exp.model_dump() if exp else None
        lines.append(f"{rule_id}: {exp.explanation}" if exp and exp.explanation
                     else f"{rule_id}: not found in the knowledge graph.")
    for doc_type in _doc_types_in(text):
        checks = kg.get_check_rules(doc_type)
        policy = kg.get_rules(doc_type)
        data.setdefault("rules", {})[doc_type] = {
            "check_rules": [r.model_dump() for r in checks],
            "policy_rules": [r.model_dump() for r in policy]}
        names = [f"{r.rule_id} {r.name}" for r in checks] + [f"{r.rule_id} {r.text}" for r in policy]
        lines.append(f"Rules for {doc_type}: " + ("; ".join(names) if names else "none in the KG."))
    if not lines:
        hits = kg.search(text)
        data["search"] = hits
        lines = ([f"{h.get('section') or h.get('standard') or 'source'}: {h.get('text', '')}"
                  for h in hits[:3]] or
                 [_NO_MATCH])
    data["kg_source"] = kg.source
    return CopilotResponse(intent="rule_query", reply="\n".join(lines), data=data)


def _summary(result) -> str:
    reviews = sum(f.review_status == "needs_more_evidence" for f in result.findings)
    return (f"Case {result.case_id} version {result.version} saved ({result.status}): "
            f"{len(result.findings)} finding(s), {reviews} need review.")


def answer(q: CopilotQuery, kg: KGClient | None = None,
           store: ResultStore | None = None) -> CopilotResponse:
    kg = kg or default_kg()
    store = store or default_store()
    intent = classify(q.text, has_docs=bool(q.docs))
    try:
        if intent == "rule_query":
            return _rule_query(q.text, kg)
        if not q.case_id:
            return CopilotResponse(intent=intent, reply="Give the case_id for this request.")
        if not q.docs:
            return CopilotResponse(intent=intent, reply=(
                "Send the documents in `docs` (same shape as POST /audit/run) to "
                + ("add them to the case." if intent == "evidence_append" else "run the audit.")))
        if intent == "evidence_append":
            if store.latest(q.case_id) is None:
                return CopilotResponse(intent=intent, reply=(
                    f"Case {q.case_id} has no saved audit yet. Ask for a fresh audit first."))
            result = orchestrator.append_evidence(q.case_id, q.docs, kg=kg, store=store)
        else:
            case = intake.normalize_case({"case_id": q.case_id, "docs": q.docs})
            result = orchestrator.run_case(case, kg=kg, store=store)
    except intake.IntakeError as exc:
        return CopilotResponse(intent=intent, reply=f"The documents could not be read: {exc}")
    except (ValueError, KGError) as exc:
        return CopilotResponse(intent=intent, reply=f"The knowledge graph could not answer: {exc}")
    return CopilotResponse(intent=intent, reply=_summary(result), data=result.model_dump())
