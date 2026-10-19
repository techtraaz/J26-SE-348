"""Review draft models (M4).

A draft line has the shape of a line in the verified record C3 reads
(Backend/Component-03/docs/c1_verified_record_contract.md), so confirming a
draft (M5) only freezes its lines. Machine fields (confidence, provenance,
escalated) are always copied from the region by the server, never taken from
the client (D2, D4).
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

# untouched: nobody acted on it · accepted: confirmed as read · edited: text or
# box changed · added: a line the engine missed · deleted: a false line, kept in
# the draft so it can be restored (left out of the verified record).
HumanAction = Literal["untouched", "accepted", "edited", "added", "deleted"]

Box = Annotated[list[int], Field(min_length=4, max_length=4)]  # [x1, y1, x2, y2], OCR-space pixels
LineText = Annotated[str, Field(max_length=2000)]

MAX_LINES = 5000


class DraftLineIn(BaseModel):
    """What the reviewer controls. `region_id` links a line to the machine
    region it came from; it is null for lines the reviewer added."""

    line_id: uuid.UUID
    region_id: uuid.UUID | None
    page: int = Field(ge=1)
    sequence: int = Field(ge=0)
    text: LineText
    box: Box
    human_action: HumanAction


class DraftLine(DraftLineIn):
    confidence: float | None  # the engine's raw score, untouched; null for added lines
    provenance: str  # engine that produced the line, or "human"
    escalated: bool | None


class ReviewDraftIn(BaseModel):
    """Full replace. `version` is the version this edit was based on (0 for
    the first save of a seeded draft)."""

    version: int = Field(ge=0)
    based_on_run_id: uuid.UUID
    lines: list[DraftLineIn] = Field(max_length=MAX_LINES)


class ReviewDraftOut(BaseModel):
    document_id: uuid.UUID
    based_on_run_id: uuid.UUID
    version: int  # 0 = seeded from the run, not saved yet
    updated_at: datetime | None
    lines: list[DraftLine]
