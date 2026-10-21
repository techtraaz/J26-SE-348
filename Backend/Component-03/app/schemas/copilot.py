"""Copilot shapes."""
from typing import Annotated, Any, Literal

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


# --- reply blocks -------------------------------------------------------------------
# A reply is a list of typed blocks built in code. Clients draw each type once (the
# frontend as lists, tables, cards and buttons); `reply` is the same content as
# Markdown for any client that only shows text.

Tone = Literal["neutral", "passed", "failed", "review", "skipped", "high", "medium", "low"]


class ListItem(BaseModel):
    label: str  # the bold lead, e.g. "CHK-001 Accounting equation"
    text: str = ""  # what follows it
    tone: Tone = "neutral"  # drawn as a status chip
    details: list[str] = Field(default_factory=list)  # sub-points


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str  # Markdown


class ListBlock(BaseModel):
    type: Literal["list"] = "list"
    title: str = ""
    items: list[ListItem] = Field(default_factory=list)
    more: int = 0  # items left out for length


class TableBlock(BaseModel):
    type: Literal["table"] = "table"
    title: str = ""
    columns: list[str]
    rows: list[list[str]]


class FindingsBlock(BaseModel):
    """Findings of a saved audit, by id; clients draw them as finding cards."""
    type: Literal["findings"] = "findings"
    title: str = ""
    finding_ids: list[str] = Field(default_factory=list)
    lines: list[str] = Field(default_factory=list)  # one plain line per finding, for text clients
    more: int = 0


class VerdictBlock(BaseModel):
    type: Literal["verdict"] = "verdict"
    case_id: str
    version: int
    verdict: str  # clean | issues_found | needs_review | not_auditable
    score: int | None = None
    summary: str = ""


class QuestionBlock(BaseModel):
    """The Copilot needs the user to choose; each choice is sent back as a message."""
    type: Literal["question"] = "question"
    text: str
    choices: list[str] = Field(default_factory=list)


class LinkBlock(BaseModel):
    type: Literal["link"] = "link"
    label: str
    url: str


Block = Annotated[TextBlock | ListBlock | TableBlock | FindingsBlock | VerdictBlock
                  | QuestionBlock | LinkBlock, Field(discriminator="type")]


class CopilotResponse(BaseModel):
    intent: str  # fine-grained intent name from the registry
    group: Group  # the proposal's category: rule_query / case_query / evidence_append / fresh_audit
    reply: str  # the blocks as Markdown
    blocks: list[Block] = Field(default_factory=list)
    session_id: str | None = None  # set when the turn was saved to a chat session
    suggestions: list[str] = Field(default_factory=list)  # follow-up questions to offer
    # Handler output plus "nlu" (how the intent was chosen), "entities", "case_id",
    # and "needs" when the request was missing something.
    data: dict[str, Any] | None = None
