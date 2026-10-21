"""Component-01 shapes, copied, not imported. Only the parts C3 reads; extra C1
fields are ignored.

- C1Extraction:     GET /api/v1/documents/{id}/extraction (exists today; machine
                    output, never edited, NOT human-verified)
- C1VerifiedRecord: GET /api/v1/documents/{id}/verified (proposed to C1, see
                    docs/c1_verified_record_contract.md; built from C1's
                    verified_records + regions + corrections tables)
"""
from typing import Literal

from pydantic import BaseModel, Field


class C1RunSummary(BaseModel):
    id: str | None = None
    status: str  # queued | running | succeeded | failed
    engine: str | None = None


class C1Region(BaseModel):
    sequence: int  # reading order within the run
    page_number: int
    text: str
    confidence: float | None = None  # raw engine score, untouched by C1
    box: list[int] = Field(default_factory=list)  # [x1, y1, x2, y2], OCR-space pixels
    provenance: str  # engine that produced it
    escalated: bool | None = None  # routed to the VLM (C1 Phase 3)
    field_key: str | None = None  # reserved in C1; not filled today


class C1Extraction(BaseModel):
    document_id: str
    run: C1RunSummary
    regions: list[C1Region] = Field(default_factory=list)


HumanAction = Literal["untouched", "accepted", "edited", "added"]


class C1VerifiedLine(BaseModel):
    line_id: str
    page: int
    sequence: int
    text: str  # as confirmed by the human
    confidence: float | None = None  # the machine's raw score, kept for analysis
    box: list[int] = Field(default_factory=list)
    provenance: str = "human"
    escalated: bool | None = None
    human_action: HumanAction = "untouched"


class C1VerifiedRecord(BaseModel):
    """Immutable human-confirmed version of a document; what C1 says downstream reads."""
    document_id: str
    version: int
    based_on_run_id: str | None = None
    confirmed_by: str | None = None
    confirmed_at: str | None = None
    lines: list[C1VerifiedLine] = Field(default_factory=list)

