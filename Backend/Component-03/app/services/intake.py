"""Intake: turn incoming JSON into a validated AuditCase before any agent runs.

Strict on identity, year, duplicates and confidence type: bad intake raises
IntakeError with a reason, never a silent drop. Lenient on content: unknown
doc types, unreadable numbers and odd confidences flow on and become visible
Data Quality findings.

Two doors:
- normalize_case(payload)  canonical case JSON {case_id, docs: [...]}
- from_c1(case_id, docs)   Component-01 extractions (GET /documents/{id}/extraction)
                           plus the doc metadata C1 does not know
"""
import re
from typing import Any

from pydantic import ValidationError

from app import config
from app.schemas.c1 import C1Document
from app.schemas.case import AuditCase, AuditDocument

INTAKE_VERSION = "canonical-v2"
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9 _\-.]{1,64}$")
_YEAR_MIN, _YEAR_MAX = 1900, 2999
# Currency prefixes/symbols OCR often glues onto a number.
_CURRENCY_RE = re.compile(r"(?i)\b(?:rs|lkr)\.?|[₨₹$€£]")
# Commas are allowed only as thousands groups: 1,234,567.89 (not "1,23").
_THOUSANDS_RE = re.compile(r"^-?\d{1,3}(,\d{3})*(\.\d+)?$|^-?\d+(\.\d+)?$")


class IntakeError(ValueError):
    """The intake payload cannot be turned into a canonical case."""


def parse_number(value: Any) -> Any:
    """'250,000' or 'Rs. 10,000.00' -> float. Anything that does not read
    cleanly stays as it was and is flagged by Data Quality (REV-003)."""
    if isinstance(value, bool) or not isinstance(value, str):
        return value
    text = _CURRENCY_RE.sub("", value).strip().replace(" ", "")
    negative = text.startswith("(") and text.endswith(")")  # accounting negatives
    if negative:
        text = text[1:-1]
    if not _THOUSANDS_RE.fullmatch(text):
        return value
    number = float(text.replace(",", ""))
    return -number if negative else number


def _confidence(value: Any, where: str) -> float:
    """A confidence must be a number. Out-of-range values are kept and flagged."""
    if isinstance(value, bool):
        raise IntakeError(f"{where}: confidence {value!r} is not a number")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise IntakeError(f"{where}: confidence {value!r} is not a number") from None


def _doc(raw: dict, case_id: str, where: str, seen: set[str]) -> AuditDocument:
    doc_id = raw.get("doc_id")
    if not isinstance(doc_id, str) or not SAFE_ID_RE.fullmatch(doc_id):
        raise IntakeError(f"{where}: invalid doc_id {doc_id!r}")
    if doc_id in seen:
        raise IntakeError(f"{where}: duplicate doc_id {doc_id!r}")
    seen.add(doc_id)

    doc_type = str(raw.get("doc_type") or "unknown").strip().lower()
    if "period_year" not in raw:
        raise IntakeError(f"{where}: period_year is required")
    year = raw["period_year"]
    if isinstance(year, bool) or not isinstance(year, int) or not _YEAR_MIN <= year <= _YEAR_MAX:
        raise IntakeError(f"{where}: period_year {year!r} must be {_YEAR_MIN}..{_YEAR_MAX}")

    fields = raw.get("fields") or {}
    if not isinstance(fields, dict):
        raise IntakeError(f"{where}: fields must be an object")
    # Only numeric fields are parsed; IDs, dates and codes stay exactly as sent.
    fields = {str(k): (parse_number(v) if k in config.NUMERIC_FIELDS else v)
              for k, v in fields.items()}

    parent = raw.get("parent_doc_id")
    if parent is not None and not isinstance(parent, str):
        raise IntakeError(f"{where}: parent_doc_id must be a string or null")
    if parent == doc_id:
        raise IntakeError(f"{where}: a document cannot be its own parent")

    confidences = raw.get("confidences") or {}
    methods = raw.get("methods") or {}
    if not isinstance(confidences, dict) or not isinstance(methods, dict):
        raise IntakeError(f"{where}: confidences and methods must be objects")
    return AuditDocument(
        doc_id=doc_id, case_id=case_id, doc_type=doc_type, period_year=year,
        parent_doc_id=parent, fields=fields,
        confidences={str(k): _confidence(v, f"{where}.{k}") for k, v in confidences.items()},
        methods={str(k): str(v) for k, v in methods.items()})


def normalize_case(payload: Any) -> AuditCase:
    """Validate and normalize a canonical case payload. Raises IntakeError."""
    raw = payload.model_dump() if isinstance(payload, AuditCase) else payload
    if not isinstance(raw, dict):
        raise IntakeError("intake must be a JSON object")
    case_id = raw.get("case_id")
    if not isinstance(case_id, str) or not SAFE_ID_RE.fullmatch(case_id):
        raise IntakeError(f"invalid case_id {case_id!r}")
    docs_raw = raw.get("docs", [])
    if not isinstance(docs_raw, list) or not all(isinstance(d, dict) for d in docs_raw):
        raise IntakeError("docs must be a list of objects")
    seen: set[str] = set()
    return AuditCase(case_id=case_id,
                     docs=[_doc(d, case_id, f"doc[{i}]", seen) for i, d in enumerate(docs_raw)])


def from_c1(case_id: str, documents: list[Any]) -> tuple[AuditCase, dict[str, int]]:
    """Map C1 extractions onto case documents.

    A region with a field_key becomes that field: value = its text, confidence =
    its raw score, method = its provenance (the engine). Two regions for the same
    field with different text keep both values (Data Quality flags the conflict)
    at the lower confidence. Regions without a field_key are counted, not used.
    Returns (case, unmapped region count per doc_id)."""
    if not isinstance(documents, list):
        raise IntakeError("documents must be a list")
    docs: list[dict] = []
    unmapped: dict[str, int] = {}
    for i, raw in enumerate(documents):
        try:
            spec = raw if isinstance(raw, C1Document) else C1Document.model_validate(raw)
        except ValidationError as exc:
            raise IntakeError(f"documents[{i}]: not a C1 extraction: {exc}") from None
        ext = spec.extraction
        if ext.run.status != "succeeded":
            raise IntakeError(f"documents[{i}]: C1 run is {ext.run.status!r}, not succeeded")
        doc_id = spec.doc_id or ext.document_id
        fields: dict[str, Any] = {}
        confidences: dict[str, float] = {}
        methods: dict[str, str] = {}
        skipped = 0
        for r in sorted(ext.regions, key=lambda r: r.sequence):
            if not r.field_key:
                skipped += 1
                continue
            key, text = r.field_key, r.text.strip()
            if key in fields:
                values = fields[key] if isinstance(fields[key], list) else [fields[key]]
                if text not in values:
                    fields[key] = [*values, text]
                    methods[key] = f"{methods[key]},{r.provenance}"
                if r.confidence is not None:
                    confidences[key] = min(confidences.get(key, r.confidence), r.confidence)
                continue
            fields[key] = text
            methods[key] = r.provenance
            if r.confidence is not None:
                confidences[key] = r.confidence
        unmapped[doc_id] = skipped
        docs.append({"doc_id": doc_id, "doc_type": spec.doc_type,
                     "period_year": spec.period_year, "parent_doc_id": spec.parent_doc_id,
                     "fields": fields, "confidences": confidences, "methods": methods})
    return normalize_case({"case_id": case_id, "docs": docs}), unmapped
