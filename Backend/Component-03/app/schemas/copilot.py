"""Copilot shapes."""
from typing import Any, Literal

from pydantic import BaseModel, Field

Intent = Literal["rule_query", "evidence_append", "fresh_audit"]


class CopilotQuery(BaseModel):
    text: str
    case_id: str | None = None
    docs: list[dict[str, Any]] = Field(default_factory=list)  # for append / fresh audit


class CopilotResponse(BaseModel):
    intent: Intent
    reply: str
    data: dict[str, Any] | None = None
