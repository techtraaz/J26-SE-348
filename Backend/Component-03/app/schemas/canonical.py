"""Canonical pipeline contract, owned by Component-03.

The case + finding JSON shapes are the agreed hand-off between components.
Component-01's OCR shapes are copied here (never imported across components,
per project rules) so the boundary is explicit: C1 emits OCR lines, C3 consumes
field-level documents.

No new data fields are invented here. Every field name matches the agreed
contract in app/schemas/case.py and app/schemas/findings.py.
"""
from typing import Any

from pydantic import BaseModel, Field

# Bump when the intake contract changes shape, so consumers can detect drift.
INTAKE_VERSION = "canonical-v1"


class OCRLine(BaseModel):
    """Copied from Component-01 (engine-agnostic extraction schema)."""

    text: str
    confidence: float
    box: tuple[int, int, int, int]
    polygon: list[tuple[int, int]]


class PageResult(BaseModel):
    """Copied from Component-01: one OCR page."""

    page_number: int
    width: int
    height: int
    lines: list[OCRLine]
    elapsed_ms: float


class EngineInfo(BaseModel):
    """Copied from Component-01: which engine produced a run."""

    name: str
    version: str
    settings: dict[str, object]


class ExtractionResult(BaseModel):
    """Copied from Component-01: what C1 emits today (OCR lines, no fields)."""

    engine: EngineInfo
    pages: list[PageResult]


class PageDocument(BaseModel):
    """A C1 page mapped to a case document, with the field values already
    read for it. C1 supplies page + doc metadata; C3 normalizes and validates.
    Fields omitted here stay empty and are flagged downstream by Data Quality."""

    page_number: int
    doc_id: str
    doc_type: str = "unknown"
    period_year: int = 2026
    parent_doc_id: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    confidences: dict[str, float] = Field(default_factory=dict)
    methods: dict[str, str] = Field(default_factory=dict)
