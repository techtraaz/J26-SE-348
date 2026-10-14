"""Copilot intent router. Keyword rules now, LLM classifier later."""
from app.schemas.copilot import CopilotQuery, CopilotResponse


def classify(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ("rule", "limit", "policy", "threshold", "standard", "clause")):
        return "rule_query"
    if any(k in t for k in ("add", "append", "new bill", "new evidence", "attach", "upload")):
        return "evidence_append"
    return "fresh_audit"


def answer(q: CopilotQuery) -> CopilotResponse:
    intent = classify(q.text)
    if intent == "rule_query":
        reply = "Rule lookup goes via KG get_rules(). Wire live KG later; mock now."
    elif intent == "evidence_append":
        reply = f"Got new evidence for case {q.case_id or 'unknown'}. Old versions are kept, new version will be made."
    else:
        reply = "Fresh audit: send case JSON to POST /audit/run."
    return CopilotResponse(intent=intent, reply=reply)  # type: ignore[arg-type]
