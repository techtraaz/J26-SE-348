"""Case shapes. One case = one balance sheet + supporting docs + past years."""
from typing import Any
from pydantic import BaseModel


class AuditDocument(BaseModel):
    doc_id: str
    case_id: str
    doc_type: str = "unknown"  # balance_sheet, income_statement, invoice, receipt, unknown
    period_year: int = 2026
    parent_doc_id: str | None = None  # which doc supports which
    fields: dict[str, Any] = {}  # numeric + text values, e.g. {"assets": 50000, "cash_out": 10000}
    confidences: dict[str, float] = {}  # per-field OCR confidence 0..1
    methods: dict[str, str] = {}  # per-field: ocr, vlm, human


class AuditCase(BaseModel):
    case_id: str
    docs: list[AuditDocument] = []
