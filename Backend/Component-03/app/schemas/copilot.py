"""Copilot shapes."""
from typing import Any, Literal

from pydantic import BaseModel, Field

# The proposal's SO5 categories; every fine-grained intent belongs to one.
Group = Literal["rule_query", "case_query", "evidence_append", "fresh_audit", "other"]


class CopilotQuery(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    case_id: str | None = None
    docs: list[dict[str, Any]] = Field(default_factory=list)  # for append / fresh audit


class CopilotResponse(BaseModel):
    intent: str  # fine-grained intent name from the registry
    group: Group  # the proposal's category: rule_query / case_query / evidence_append / fresh_audit
    reply: str
    suggestions: list[str] = Field(default_factory=list)  # follow-up questions to offer
    # Handler output plus "nlu" (how the intent was chosen), "entities", "case_id",
    # and "needs" when the request was missing something.
    data: dict[str, Any] | None = None
