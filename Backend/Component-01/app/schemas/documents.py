"""API response models for documents and their extraction results."""

import uuid
from datetime import datetime

from pydantic import BaseModel

class RunSummary(BaseModel):
    id: uuid.UUID
    status: str  # queued | running | succeeded | failed
    pipeline_mode: str
    engine: str | None  # provenance: which engine produced the result
    pages_total: int | None
    pages_done: int
    elapsed_ms: float | None
    started_at: datetime | None
    finished_at: datetime | None

class DocumentOut(BaseModel):
    id: uuid.UUID
    folder_id: uuid.UUID | None
    filename: str
    mime: str
    sha256: str
    # uploaded | processing | needs_review | verified | failed
    status: str
    page_count: int | None
    source: str  # demo | research
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    latest_run: RunSummary | None

class PageOut(BaseModel):
    page_number: int
    width: int  # pixel size of the OCR-space image the region boxes refer to
    height: int
    dpi: int | None
    image_url: str

class DocumentDetail(DocumentOut):
    pages: list[PageOut]

class DocumentList(BaseModel):
    items: list[DocumentOut]
    total: int
    limit: int
    offset: int

class RegionOut(BaseModel):
    id: uuid.UUID
    sequence: int  # reading order across the whole run
    page_number: int
    text: str
    confidence: float | None  # raw engine score, untouched
    box: list[int]  # [x1, y1, x2, y2] in OCR-space pixels
    polygon: list[list[int]] | None
    provenance: str
    escalated: bool | None
    field_key: str | None

class ExtractionOut(BaseModel):
    document_id: uuid.UUID
    run: RunSummary
    pages: list[PageOut]
    regions: list[RegionOut]