"""Intake: turn incoming JSON into a validated AuditCase before any agent runs.

Strict on identity, year, duplicates and confidence type: bad intake raises
IntakeError with a reason, never a silent drop. Lenient on content: unknown
doc types, unreadable numbers and odd confidences flow on and become visible
Data Quality findings.

normalize_case(payload) takes canonical case JSON {case_id, docs: [...]}.
Component-01 documents reach it through the review flow (app.services.c1_review).
"""
import re
from typing import Any

from pydantic import ValidationError

from app import config
from app.schemas.case import AuditCase, AuditDocument, DocumentSource

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
    source = raw.get("source")
    if source is not None:
        try:
            source = DocumentSource.model_validate(source)
        except ValidationError as exc:
            raise IntakeError(f"{where}: invalid source: {exc.errors()[0]['msg']}") from None
    return AuditDocument(
        doc_id=doc_id, case_id=case_id, doc_type=doc_type, period_year=year,
        parent_doc_id=parent, fields=fields,
        confidences={str(k): _confidence(v, f"{where}.{k}") for k, v in confidences.items()},
        methods={str(k): str(v) for k, v in methods.items()}, source=source)


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
    materiality = raw.get("materiality")
    if materiality is not None:
        materiality = parse_number(materiality)
        if isinstance(materiality, bool) or not isinstance(materiality, (int, float)) or materiality < 0:
            raise IntakeError(f"materiality {raw.get('materiality')!r} must be a positive amount")
    seen: set[str] = set()
    return AuditCase(case_id=case_id, materiality=float(materiality) if materiality is not None else None,
                     docs=[_doc(d, case_id, f"doc[{i}]", seen) for i, d in enumerate(docs_raw)])
