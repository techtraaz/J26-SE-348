"""Session memory for follow-up questions. Deterministic, no LLM.

    apply(entities, text, memory)  fill what a follow-up leaves out
    update(memory, response)       remember what this turn was about

"why did that one fire?"   -> the findings shown last
"show only the high ones"  -> the last list's filters plus severity high
no case named              -> the case discussed last (handled by the caller)
"""
import re

from app.schemas.chat import FindingFilters, SessionContext
from app.schemas.copilot import CopilotResponse
from app.services.copilot.entities import Entities

# Pointing back at what was just shown ("this case" / "that audit" are not findings).
_REFERS_BACK = re.compile(r"\b(it|its|that( one)?|this one|those|them|they|the same|above)\b"
                          r"(?!\s+(case|audit|version|document|rule))", re.IGNORECASE)
# Narrowing the last list.
_NARROWS = re.compile(r"\b(only|just|also|of (those|these|them)|among (them|those|these))\b", re.IGNORECASE)
_FILTERS = ("severities", "rule_ids", "doc_ids", "doc_types", "categories", "review_statuses")


def refers_back(text: str) -> bool:
    return _REFERS_BACK.search(text) is not None


def apply(entities: Entities, text: str, memory: SessionContext | None) -> Entities:
    if memory is None:
        return entities
    names_a_finding = entities.rule_ids or entities.doc_ids
    if memory.finding_ids and not names_a_finding and refers_back(text):
        entities.finding_ids = list(memory.finding_ids)
    if _NARROWS.search(text):
        for name in _FILTERS:
            if not getattr(entities, name):
                setattr(entities, name, list(getattr(memory.filters, name)))
    return entities


def update(memory: SessionContext, response: CopilotResponse) -> SessionContext:
    """The next turn's memory. Keeps earlier values when this turn says nothing new."""
    data = response.data or {}
    if data.get("needs"):
        return memory  # the request was incomplete; nothing new was shown
    new = memory.model_copy(deep=True)
    case_id = data.get("case_id")
    if case_id and case_id != new.case_id:
        new = SessionContext(case_id=case_id)
    version = data.get("version") or data.get("to")
    if version and not data.get("unsaved"):
        new.version = int(version)
    new.last_intent = response.intent
    findings = data.get("findings")
    if findings:
        new.finding_ids = [f["finding_id"] for f in findings]
    if isinstance(data.get("filters"), dict):
        new.filters = FindingFilters.model_validate(data["filters"])
    return new
