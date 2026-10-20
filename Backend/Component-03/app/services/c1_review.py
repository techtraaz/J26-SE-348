"""Library review of Component-01 documents before they are audited.

preview()  -> what C3 read from each document (fields with their source lines,
              suggested type and year, unused numeric lines, missing fields).
              Nothing is saved.
confirm()  -> the reviewer's decisions become AuditDocuments. Everything is
              recomputed here: a value always comes from its cited line (or from
              the reviewer typing it), and confidence is decided by C3, never
              taken from the client.

Confidence of a field (see config):
- value from a human-verified C1 record          -> 1.0 (a person confirmed it)
- value from machine extraction                  -> lowest raw score of its lines
- matched by the LLM and not confirmed by a person -> capped at
  UNCONFIRMED_MAPPING_CONFIDENCE, so it becomes a REV-001 review item
- typed by the reviewer                          -> 1.0
"""
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app import config
from app.schemas.c1 import C1Extraction, C1VerifiedRecord
from app.schemas.case import DocumentSource
from app.services import field_mapper as fm
from app.services import intake, rules
from app.services.kg_client import KGClient


class C1Input(BaseModel):
    """One document as C1 provides it: its verified record when a person has
    verified it, otherwise its machine extraction."""
    verified: C1VerifiedRecord | None = None
    extraction: C1Extraction | None = None
    doc_type: str | None = None  # the reviewer's choice; suggested when absent
    name: str | None = Field(None, max_length=255)  # C1's file name, shown in reports

    @model_validator(mode="after")
    def _one_source(self):
        if self.verified is None and self.extraction is None:
            raise ValueError("send the C1 verified record or extraction")
        if self.extraction is not None and self.extraction.run.status != "succeeded":
            raise ValueError(f"C1 run is {self.extraction.run.status!r}, not succeeded")
        return self


class FieldDecision(BaseModel):
    field: str
    line_id: str | None = None  # the line holding the value
    value: float | str | None = None  # set only when the reviewer typed or changed it
    confirmed: bool = False  # the reviewer checked an AI or hand-picked match


class ReviewedDocument(C1Input):
    doc_id: str | None = None  # defaults to C1's document_id
    period_year: int  # required: the reviewer confirms the year
    parent_doc_id: str | None = None
    fields: list[FieldDecision] = Field(default_factory=list)


# --- shared ------------------------------------------------------------------------

def _lines(doc: C1Input) -> tuple[list[fm.Line], DocumentSource, dict[str, fm.Line]]:
    lines, source = fm.read_record(doc.extraction, doc.verified)
    return lines, source, {ln.line_id: ln for ln in lines}


def line_confidence(*lines: fm.Line | None) -> float:
    """1.0 for human-verified lines; else the lowest known raw score (1.0 if none)."""
    known = [ln.confidence for ln in lines if ln is not None and not ln.verified and ln.confidence is not None]
    return round(min(known), 4) if known else 1.0


def _origin(line: fm.Line, source: DocumentSource) -> str:
    if source.human_verified:
        return f"c1-verified-v{source.verified_version}:{line.line_id}"
    return f"c1:{line.provenance}:{line.line_id}"


def field_names(kg: KGClient) -> list[str]:
    """Names a reviewer may give a field: C2's line items plus C3's everyday fields."""
    return sorted(set(kg.get_field_map().values()) | set(fm.EVERYDAY_LABELS.values())
                  | {fm.APPROVALS_FIELD})


def _ref(line: fm.Line | None) -> dict[str, Any] | None:
    if line is None:
        return None
    return {"line_id": line.line_id, "page": line.page, "text": line.text,
            "confidence": line.confidence, "box": list(line.box) if line.box else None}


# --- preview -------------------------------------------------------------------------

def preview(case_id: str, documents: list[C1Input], kg: KGClient) -> list[dict]:
    out = []
    names = field_names(kg)
    for doc in documents:
        lines, source, by_id = _lines(doc)
        mapping = fm.map_document(lines, doc.doc_type, kg)
        fields = []
        for f in mapping.fields.values():
            value_line, label_line = by_id[f.line_id], by_id.get(f.label_line_id or "")
            ai = f.method == "llm"
            conf = (_approvals(lines, by_id, 0)[1] if f.field == fm.APPROVALS_FIELD
                    else line_confidence(value_line, label_line))
            fields.append({
                "field": f.field, "value": f.value, "method": f.method, "label": f.label,
                "needs_confirmation": ai,
                "confidence": min(conf, config.UNCONFIRMED_MAPPING_CONFIDENCE) if ai else conf,
                "line": _ref(value_line), "label_line": _ref(label_line),
                "alternatives": f.alternatives})
        doc_type = doc.doc_type or (mapping.doc_type.value if mapping.doc_type else "unknown")
        out.append({
            "document_id": source.document_id, "name": doc.name, "source": source.model_dump(),
            "human_verified": source.human_verified,
            "suggestions": {
                "doc_type": mapping.doc_type.__dict__ if mapping.doc_type else None,
                "period_year": mapping.period_year.__dict__ if mapping.period_year else None},
            "doc_type": doc_type, "fields": fields,
            "unmapped_lines": [{**_ref(ln), "value": fm.first_amount(ln.text)} for ln in mapping.unmapped],
            "missing_fields": mapping.missing, "rules_not_runnable": mapping.rules_not_runnable,
            "field_names": names, "llm": {"used": mapping.llm_used, "error": mapping.llm_error},
            "line_count": len(lines)})
    return out


# --- confirm -------------------------------------------------------------------------

def _value(decision: FieldDecision, line: fm.Line | None) -> tuple[float | str, bool]:
    """(value, typed by the reviewer). A value is read from its line unless typed."""
    if decision.value is not None:
        if decision.field in config.NUMERIC_FIELDS and isinstance(decision.value, str):
            parsed = intake.parse_number(decision.value)
            if not isinstance(parsed, float):
                raise intake.IntakeError(f"{decision.field}: {decision.value!r} is not a number")
            return parsed, True
        return decision.value, True
    if line is None:
        raise intake.IntakeError(f"{decision.field}: give a line_id or a value")
    if decision.field in fm.TEXT_FIELDS:
        text = fm.text_value(decision.field, line.text)
        if text is None:
            raise intake.IntakeError(f"{decision.field}: line {line.line_id} holds no such value")
        return text, False
    number = fm.first_amount(line.text)
    if number is None:
        raise intake.IntakeError(f"{decision.field}: line {line.line_id} holds no amount")
    return number, False


def _approvals(lines: list[fm.Line], by_id: dict[str, fm.Line], i: int) -> tuple[float, float]:
    """(signed approval rows, lowest confidence of the stamp lines)."""
    rows = fm.read_approvals(lines)
    if not rows:
        raise intake.IntakeError(f"documents[{i}]: no approval rows found; type the count as a value")
    stamp = [by_id[lid] for r in rows for lid in r.line_ids]
    return float(sum(r.signed for r in rows)), line_confidence(*stamp)


def confirm(case_id: str, documents: list[ReviewedDocument], kg: KGClient) -> list[dict]:
    """Reviewed documents as raw case documents (validated by intake afterwards)."""
    allowed = set(field_names(kg))
    raw_docs = []
    for i, doc in enumerate(documents):
        lines, source, by_id = _lines(doc)
        by_rules = fm.map_by_rules(lines, fm.lexicon(kg.get_field_map()))
        fields: dict[str, Any] = {}
        confidences: dict[str, float] = {}
        methods: dict[str, str] = {}
        for d in doc.fields:
            if d.field not in allowed:
                raise intake.IntakeError(f"documents[{i}]: {d.field!r} is not a known field name")
            if d.field in fields:
                raise intake.IntakeError(f"documents[{i}]: {d.field!r} given twice")
            line = by_id.get(d.line_id) if d.line_id else None
            if d.line_id and line is None:
                raise intake.IntakeError(f"documents[{i}]: line {d.line_id!r} is not in the C1 record")
            if d.field == fm.APPROVALS_FIELD and d.value is None:
                fields[d.field], confidences[d.field] = _approvals(lines, by_id, i)
                methods[d.field] = "c3:rules"
                continue
            value, typed = _value(d, line)
            rule_hit = by_rules.get(d.field)
            how: Literal["human", "rules", "confirmed", "unconfirmed"]
            if typed:
                how, conf = "human", 1.0
            elif rule_hit and rule_hit.line_id == d.line_id:
                how = "rules"
                conf = line_confidence(line, by_id.get(rule_hit.label_line_id or ""))
            elif d.confirmed:
                how, conf = "confirmed", line_confidence(line)
            else:
                how = "unconfirmed"
                conf = min(line_confidence(line), config.UNCONFIRMED_MAPPING_CONFIDENCE)
            fields[d.field] = value
            confidences[d.field] = conf
            methods[d.field] = (f"{_origin(line, source)}|" if line else "") + f"c3:{how}"
        raw_docs.append({
            "doc_id": doc.doc_id or source.document_id, "name": doc.name,
            "doc_type": doc.doc_type or "unknown",
            "period_year": doc.period_year, "parent_doc_id": doc.parent_doc_id,
            "fields": fields, "confidences": confidences, "methods": methods,
            "source": source.model_dump()})
    return raw_docs


def confirm_case(case_id: str, documents: list[ReviewedDocument], kg: KGClient) -> dict:
    """Confirmed documents, checked by intake, with the Data Quality issues they will raise."""
    case = intake.normalize_case({"case_id": case_id, "docs": confirm(case_id, documents, kg)})
    return {"case": case.model_dump(), "issues": [f.message for f in rules.data_quality_findings(case)]}
