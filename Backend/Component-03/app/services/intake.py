"""Canonical intake: turn incoming case JSON into a validated AuditCase.

C1 emits OCR lines; this layer is where C1's page output is mapped to
field-level documents and where the case contract is enforced before agents run.

Strict on identity, year, duplicates and confidence (bad intake raises
IntakeError with a reason — never a silent drop). Lenient on doc_type: an
unknown or unsupported type still flows to the needs-review path instead of
being rejected at the door.
"""
import re
from typing import Any

from app import config
from app.schemas.canonical import INTAKE_VERSION, ExtractionResult, PageDocument
from app.schemas.case import AuditCase, AuditDocument

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9 _\-.]{1,64}$")
_YEAR_MIN, _YEAR_MAX = 1900, 2999
# Currency prefixes/symbols OCR often glues onto a number.
_CURRENCY_RE = re.compile(r"(?i)\b(?:rs|lkr)\.?|[₨₹$€£]")


class IntakeError(ValueError):
    """The intake payload cannot be turned into a canonical case."""


def _conf(value: Any, where: str) -> float:
    """Coerce a confidence to a float, or raise a clear error. A value outside
    0..1 is kept as-is and flagged by validate_case, never silently clamped."""
    try:
        return float(value)
    except (TypeError, ValueError):
        raise IntakeError(f"{where}: confidence {value!r} is not a number") from None


def _parse_number(value: Any) -> Any:
    """Turn a numeric string like '250,000' or 'Rs. 10,000.00' into a float.
    Anything that does not read cleanly as a number is returned unchanged."""
    if isinstance(value, bool) or not isinstance(value, str):
        return value
    text = _CURRENCY_RE.sub("", value).strip().replace(",", "").strip()
    if not any(ch.isdigit() for ch in text):
        return value
    try:
        return float(text)
    except ValueError:
        return value


def _one_doc(raw: dict, case_id: str, where: str, seen: set[str]) -> AuditDocument:
    doc_id = raw.get("doc_id")
    if not isinstance(doc_id, str) or not SAFE_ID_RE.fullmatch(doc_id):
        raise IntakeError(f"{where}: invalid doc_id {doc_id!r}")
    if doc_id in seen:
        raise IntakeError(f"{where}: duplicate doc_id {doc_id!r}")
    seen.add(doc_id)

    doc_type = str(raw.get("doc_type", "unknown")).strip().lower() or "unknown"
    # No silent default: the document's year must be stated, never guessed.
    if "period_year" not in raw:
        raise IntakeError(f"{where}: period_year is required")
    year = raw["period_year"]
    if not isinstance(year, int) or isinstance(year, bool) or not (_YEAR_MIN <= year <= _YEAR_MAX):
        raise IntakeError(f"{where}: period_year {year!r} must be {_YEAR_MIN}..{_YEAR_MAX}")

    fields = raw.get("fields") or {}
    if not isinstance(fields, dict):
        raise IntakeError(f"{where}: fields must be an object")
    fields = {k: _parse_number(v) for k, v in fields.items()}
    parent = raw.get("parent_doc_id")
    if parent is not None and not isinstance(parent, str):
        raise IntakeError(f"{where}: parent_doc_id must be a string or null")

    confidences: dict[str, float] = {}
    for k, v in (raw.get("confidences") or {}).items():
        confidences[str(k)] = _conf(v, f"{where}.{k}")
    methods = {str(k): str(v) for k, v in (raw.get("methods") or {}).items()}

    return AuditDocument(
        doc_id=doc_id, case_id=case_id, doc_type=doc_type, period_year=year,
        parent_doc_id=parent, fields=dict(fields),
        confidences=confidences, methods=methods)


def normalize_case(payload: dict | AuditCase) -> AuditCase:
    """Validate and normalize a canonical case payload. Raises IntakeError."""
    if isinstance(payload, AuditCase):
        raw = payload.model_dump()
    elif isinstance(payload, dict):
        raw = payload
    else:
        raise IntakeError("intake must be a JSON object")

    case_id = raw.get("case_id")
    if not isinstance(case_id, str) or not SAFE_ID_RE.fullmatch(case_id):
        raise IntakeError(f"invalid case_id {case_id!r}")

    docs_raw = raw.get("docs", [])
    if not isinstance(docs_raw, list):
        raise IntakeError("docs must be a list")

    seen: set[str] = set()
    docs = [_one_doc(d, case_id, f"doc[{i}]", seen)
            for i, d in enumerate(docs_raw) if isinstance(d, dict)]
    if len(docs) != len(docs_raw):
        raise IntakeError("every doc must be an object")
    return AuditCase(case_id=case_id, docs=docs)


def validate_case(case: AuditCase) -> list[str]:
    """Non-fatal issues an auditor should know about. Never drops anything."""
    ids = {d.doc_id for d in case.docs}
    issues: list[str] = []
    for d in case.docs:
        if d.parent_doc_id is not None and d.parent_doc_id not in ids:
            issues.append(f"doc {d.doc_id}: parent_doc_id {d.parent_doc_id!r} not in case")
        if d.doc_type not in config.ALLOWED_DOC_TYPES:
            issues.append(f"doc {d.doc_id}: doc_type {d.doc_type!r} not supported by the KG")
        for fname, value in d.fields.items():
            if fname in config.NUMERIC_FIELDS and isinstance(value, str):
                issues.append(f"doc {d.doc_id}: field {fname!r} value {value!r} "
                              f"could not be read as a number")
        for fname, conf in d.confidences.items():
            if not 0.0 <= conf <= 1.0:
                issues.append(f"doc {d.doc_id}: confidence for {fname!r} outside 0..1")
    return issues


def from_extraction(extraction: ExtractionResult | dict, case_id: str,
                    page_documents: list[PageDocument | dict]) -> AuditCase:
    """Bridge C1 output: map its OCR pages onto field-level case documents.

    Each PageDocument names the page it came from; field values come from C1's
    field step (supplied here). A mapping that points at a page the extraction
    does not contain is rejected."""
    if isinstance(extraction, dict):
        extraction = ExtractionResult.model_validate(extraction)
    pages = {p.page_number for p in extraction.pages}

    raw = {"case_id": case_id, "docs": []}
    for i, spec in enumerate(page_documents):
        doc = spec if isinstance(spec, PageDocument) else PageDocument.model_validate(spec)
        if doc.page_number not in pages:
            raise IntakeError(
                f"doc[{i}]: page_number {doc.page_number} not in extraction")
        methods = doc.methods or {f: "ocr" for f in doc.fields}
        raw["docs"].append({
            "doc_id": doc.doc_id, "doc_type": doc.doc_type,
            "period_year": doc.period_year, "parent_doc_id": doc.parent_doc_id,
            "fields": doc.fields, "confidences": doc.confidences,
            "methods": methods})
    return normalize_case(raw)


__all__ = [
    "INTAKE_VERSION",
    "IntakeError",
    "from_extraction",
    "normalize_case",
    "validate_case",
]
