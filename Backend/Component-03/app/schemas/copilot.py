"""Copilot shapes."""
from typing import Any, Literal

from pydantic import BaseModel, Field

# The proposal's SO5 categories; every fine-grained intent belongs to one.
Group = Literal["rule_query", "case_query", "evidence_append", "fresh_audit", "other"]


SESSION_ID_PATTERN = r"^[A-Za-z0-9 _\-.]{1,64}$"


class CopilotQuery(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    case_id: str | None = None
    # With a session the conversation is saved and follow-ups use its memory.
    session_id: str | None = Field(default=None, pattern=SESSION_ID_PATTERN)
    docs: list[dict[str, Any]] = Field(default_factory=list)  # for append / fresh audit


class CopilotResponse(BaseModel):
    intent: str  # fine-grained intent name from the registry
    group: Group  # the proposal's category: rule_query / case_query / evidence_append / fresh_audit
    reply: str
    session_id: str | None = None  # set when the turn was saved to a chat session
    suggestions: list[str] = Field(default_factory=list)  # follow-up questions to offer
    # Handler output plus "nlu" (how the intent was chosen), "entities", "case_id",
    # and "needs" when the request was missing something.
    data: dict[str, Any] | None = None
