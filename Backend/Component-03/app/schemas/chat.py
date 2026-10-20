"""Chat shapes: sessions, messages and the structured session memory."""
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.copilot import Block, Group
from app.schemas.findings import Finding, now_iso

Role = Literal["user", "copilot", "report", "system"]


class FindingFilters(BaseModel):
    """The filters the last finding list used; a follow-up can narrow them."""
    severities: list[str] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)
    doc_ids: list[str] = Field(default_factory=list)
    doc_types: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    review_statuses: list[str] = Field(default_factory=list)


class SessionContext(BaseModel):
    """What the conversation is about, updated in code after every turn.
    Follow-ups ("why did that fire?", "only the high ones") resolve against it."""
    case_id: str | None = None
    version: int | None = None
    last_intent: str | None = None
    finding_ids: list[str] = Field(default_factory=list)
    filters: FindingFilters = Field(default_factory=FindingFilters)

    def summary(self) -> str:
        if not self.case_id and not self.last_intent:
            return ""
        parts = [f"case {self.case_id}" + (f" v{self.version}" if self.version else "")] if self.case_id else []
        if self.last_intent:
            parts.append(f"last request {self.last_intent}")
        if self.finding_ids:
            parts.append(f"{len(self.finding_ids)} finding(s) shown")
        return "Conversation so far: " + ", ".join(parts) + "."


class ChatSession(BaseModel):
    session_id: str
    case_id: str | None = None  # the case this chat belongs to; None = general chat
    title: str = ""
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    context: SessionContext = Field(default_factory=SessionContext)


class ChatRename(BaseModel):
    """A new chat title from the auditor; empty puts the default back (the case id)."""
    title: str = Field(default="", max_length=80)
    case_id: str | None = None  # the case the chat belongs to, for a chat not saved yet


class MessageRefs(BaseModel):
    """Findings the message is about, by reference into a saved audit version."""
    version: int | None = None
    finding_ids: list[str] = Field(default_factory=list)


class ChatMessage(BaseModel):
    message_id: str
    session_id: str
    seq: int = 0  # order within the session, assigned by the store (timestamps can tie)
    case_id: str | None = None
    role: Role
    text: str  # Markdown; the same content as `blocks` for clients that only show text
    blocks: list[Block] = Field(default_factory=list)  # Copilot replies: what the UI draws
    intent: str | None = None
    group: Group | None = None
    suggestions: list[str] = Field(default_factory=list)
    refs: MessageRefs | None = None
    # Only findings that live in no saved audit (what-if checks). Saved findings
    # are filled in from `refs` when history is read.
    findings: list[Finding] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)  # small extras, e.g. a report link
    source: str = "c3"  # which component wrote it (c3, c4, ...)
    created_at: str = Field(default_factory=now_iso)


class ExternalMessage(BaseModel):
    """What another component (e.g. C4 with a finished report) posts into a case's chat."""
    role: Literal["report", "system"] = "report"
    text: str = Field(min_length=1, max_length=4000)
    version: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="c4", min_length=1, max_length=32)
