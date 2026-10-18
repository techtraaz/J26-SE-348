"""Shapes of Component-02's KG query API replies (docs/query_api.md in C2).

Copied, not imported, per project rules. Every live reply is validated against
these; anything that does not fit is a protocol error, never silently accepted.
"""
from pydantic import BaseModel, Field

from app.schemas.findings import Severity


class RuleResponse(BaseModel):
    """GET /query/rules/{doc_type}: a policy rule with a numeric limit."""
    rule_id: str
    text: str = ""
    limit: float | None = None


class RuleVariable(BaseModel):
    """What a name in a check-rule expression means and its other names."""
    name: str
    line_item: str = ""
    aliases: list[str] = Field(default_factory=list)


class CheckRuleResponse(BaseModel):
    """GET /query/check-rules/{doc_type}: a machine-checkable rule."""
    rule_id: str
    name: str = ""
    expression: str
    severity: Severity = "medium"
    variables: list[RuleVariable] = Field(default_factory=list)


class Citation(BaseModel):
    """One source a rule comes from (a standard, maybe a paragraph)."""
    standard: str | None = None
    title: str | None = None
    paragraph: str | None = None
    section: str | None = None
    heading: str | None = None
    text: str | None = None

    @property
    def ref(self) -> str:
        return self.section or self.standard or ""


class RuleExplanation(BaseModel):
    """GET /query/rules/{rule_id}/explain (only the parts C3 uses)."""
    citations: list[Citation] = Field(default_factory=list)
    explanation: str = ""
