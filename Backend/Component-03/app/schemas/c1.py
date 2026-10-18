"""Component-01 extraction shapes (app/schemas/documents.py in C1), copied, not
imported. Only the parts C3 reads; extra C1 fields are ignored."""
from pydantic import BaseModel, Field


class C1RunSummary(BaseModel):
    status: str  # queued | running | succeeded | failed
    engine: str | None = None


class C1Region(BaseModel):
    sequence: int
    page_number: int
    text: str
    confidence: float | None = None  # raw engine score, untouched by C1
    provenance: str  # engine that produced it
    escalated: bool | None = None  # routed to the VLM (C1 Phase 3)
    field_key: str | None = None  # which document field this region is


class C1Extraction(BaseModel):
    """GET /documents/{id}/extraction in C1."""
    document_id: str
    run: C1RunSummary
    regions: list[C1Region] = Field(default_factory=list)


class C1Document(BaseModel):
    """One C1 extraction plus the case metadata C1 does not know."""
    extraction: C1Extraction
    doc_id: str | None = None  # defaults to C1's document_id
    doc_type: str = "unknown"
    period_year: int  # required: the period is never guessed
    parent_doc_id: str | None = None
