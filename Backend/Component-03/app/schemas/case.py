"""Case shapes. One case = the documents of one audit (statements, supporting docs, past years)."""
from typing import Any

from pydantic import BaseModel, Field


class AuditDocument(BaseModel):
    doc_id: str
    case_id: str
    doc_type: str = "unknown"  # a C2 DocumentType code, or unknown
    period_year: int
    parent_doc_id: str | None = None  # the document this one supports
    fields: dict[str, Any] = Field(default_factory=dict)
    confidences: dict[str, float] = Field(default_factory=dict)  # per field, 0..1
    methods: dict[str, str] = Field(default_factory=dict)  # per field: C1 engine, or human


class AuditCase(BaseModel):
    case_id: str
    docs: list[AuditDocument] = Field(default_factory=list)
