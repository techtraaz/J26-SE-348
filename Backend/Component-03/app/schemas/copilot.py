"""Copilot shapes. Keyword router now, LLM intent later."""
from typing import Literal
from pydantic import BaseModel

Intent = Literal["rule_query", "evidence_append", "fresh_audit"]


class CopilotQuery(BaseModel):
    text: str
    case_id: str | None = None


class CopilotResponse(BaseModel):
    intent: Intent
    reply: str
