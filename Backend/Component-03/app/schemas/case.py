"""Case shapes. One case = the documents of one audit (statements, supporting docs, past years)."""
from typing import Any

from pydantic import BaseModel, Field


class DocumentSource(BaseModel):
    """Where a document's values came from, so every audit traces back to the
    exact upstream record."""
    component: str = "c1"
    document_id: str
    run_id: str | None = None
    verified_version: int | None = None  # None = machine extraction, not human-verified
    confirmed_by: str | None = None

    @property
    def human_verified(self) -> bool:
        return self.verified_version is not None


class AuditDocument(BaseModel):
    doc_id: str
    case_id: str
    name: str | None = None  # what people call it, e.g. C1's file name; never used in checks
    doc_type: str = "unknown"  # a C2 DocumentType code, or unknown
    period_year: int
    parent_doc_id: str | None = None  # the document this one supports
    fields: dict[str, Any] = Field(default_factory=dict)
    confidences: dict[str, float] = Field(default_factory=dict)  # per field, 0..1
    methods: dict[str, str] = Field(default_factory=dict)  # per field: where the value came from
    source: DocumentSource | None = None  # None = values sent directly (no upstream record)


class AuditCase(BaseModel):
    case_id: str
    docs: list[AuditDocument] = Field(default_factory=list)
    # Amount below which a misstatement is not material (SLAuS 320), set by the
    # auditor per case. None = every difference counts at the rule's severity.
    materiality: float | None = None
