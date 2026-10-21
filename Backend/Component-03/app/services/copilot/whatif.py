"""What-if: turn a described transaction into a temporary document for the real
checks. "Paid Rs 150,000 cash for a laptop, booked on credit, no asset recorded"
-> invoice {amount: 150000, cash_out: 150000, purchase_basis: credit, asset_in: 0}.

Two readers, both checked against the text:
- cue rules (always): a field label next to an amount ("assets of 50,000")
- the LLM (when available): maps wording to field names; every number it gives
  must be an amount written in the text (or 0 when the text says "no"/"without"),
  and every word value must appear in the text. Anything else is dropped.
Values are read, never decided: the verdict still comes from the Python checks.
"""
import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import create_model

from app import config
from app.services import llm
from app.services.copilot.entities import Amount, Entities

_NEGATION = re.compile(r"\b(no|not|without|never|nothing|none)\b", re.IGNORECASE)
FIELD_CUES: dict[str, str] = {
    "cash_out": r"\b(paid|pay(ment)?|cash (out|paid)|spent|withdrew)\b",
    "amount": r"\b(invoice|bill|amount|purchase[ds]?|bought|total|worth|cost|price)\b",
    "assets": r"\b(total )?assets?\b",
    "liabilities": r"\bliabilit(y|ies)\b",
    "capital": r"\b(capital|equity)\b",
    "debit_total": r"\b(total )?debits?\b",
    "credit_total": r"\b(total credits?|credits? total)\b",
    "revenue": r"\b(revenue|sales|turnover)\b",
    "cost_of_sales": r"\b(cost of sales|cogs)\b",
    "gross_profit": r"\bgross profit\b",
    "inventories": r"\binventor(y|ies)\b",
    "inventory_nrv": r"\b(nrv|net realisable value)\b",
}
_CREDIT = re.compile(r"\b(on|as|in) credit\b|\bcredit (purchase|basis)\b|\bbooked\b[^.]*\bcredit\b", re.IGNORECASE)
_CASH = re.compile(r"\b(on|as|in) cash\b|\bcash (purchase|basis)\b|\bbooked\b[^.]*\bcash\b", re.IGNORECASE)
_NO_ASSET = re.compile(r"\b(no|without|not)\b[^.]{0,30}\bassets?\b|\bassets?\b[^.]{0,20}\bnot\b", re.IGNORECASE)
_YEAR = re.compile(r"\b(19|20)\d{2}\b")


def _zones(text: str, amounts: list[Amount]) -> list[tuple[str, str]]:
    """For each amount: the text before it (since the previous amount) and after it."""
    spans, pos = [], 0
    for a in amounts:
        start = text.find(a.text, pos)
        spans.append((start, start + len(a.text)))
        pos = start + len(a.text)
    out = []
    for i, (s, e) in enumerate(spans):
        before = text[(spans[i - 1][1] if i else 0):s]
        after = text[e:(spans[i + 1][0] if i + 1 < len(spans) else len(text))]
        out.append((before, re.split(r"[,.;]| and ", after, maxsplit=1)[0]))
    return out


def _closest_cue(zone: str, before_amount: bool) -> str | None:
    """The field whose label sits nearest the amount; a longer label wins a tie
    ('credit total' beats 'total')."""
    best: tuple[int, int, str] | None = None
    for name, pattern in FIELD_CUES.items():
        for m in re.finditer(pattern, zone, re.IGNORECASE):
            nearness = m.end() if before_amount else -m.start()
            key = (nearness, m.end() - m.start(), name)
            if best is None or key[:2] > best[:2]:
                best = key
    return best[2] if best else None


def read_by_cues(text: str, amounts: list[Amount]) -> dict[str, float | str]:
    fields: dict[str, float | str] = {}
    for a, (before, after) in zip(amounts, _zones(text, amounts), strict=True):
        name = _closest_cue(before, True) or _closest_cue(after, False)
        if name:
            fields.setdefault(name, a.value)
    if "cash_out" in fields and "amount" not in fields:
        fields["amount"] = fields["cash_out"]  # "paid 150,000 for a laptop": the purchase value
    if _CREDIT.search(text):
        fields["purchase_basis"] = "credit"
    elif _CASH.search(text):
        fields["purchase_basis"] = "cash"
    if _NO_ASSET.search(text):
        fields["asset_in"] = 0.0
    return fields


def _llm_model():
    doc_types = tuple(sorted(config.ALLOWED_DOC_TYPES - {"unknown"}))
    spec = {f: (float | None, None) for f in sorted(config.NUMERIC_FIELDS)}
    spec["purchase_basis"] = (Literal["cash", "credit"] | None, None)
    spec["doc_type"] = (Literal[doc_types] | None, None)  # type: ignore[valid-type]
    return create_model("WhatIfFields", **spec)


def read_by_llm(text: str, amounts: list[Amount]) -> tuple[dict[str, float | str], str | None]:
    """(verified fields, doc_type). Raises llm.LLMError."""
    out = llm.complete_json(
        "Read a described financial transaction into document fields. Use only numbers "
        "written in the text. Use 0 only when the text says something is absent. Leave "
        "every field you are not sure of null.", text, _llm_model())
    written = [a.value for a in amounts]
    negated = bool(_NEGATION.search(text))
    fields: dict[str, float | str] = {}
    for name, value in out.model_dump(exclude={"doc_type"}).items():
        if value is None:
            continue
        if isinstance(value, str):
            if re.search(rf"\b{re.escape(value)}\b", text, re.IGNORECASE):
                fields[name] = value
        elif any(abs(value - w) <= 0.5 for w in written) or (value == 0 and negated):
            fields[name] = float(value)
    return fields, out.doc_type


def _infer_doc_type(fields: dict, entities: Entities) -> str:
    if len(entities.doc_types) == 1:
        return entities.doc_types[0]
    if {"assets", "liabilities", "capital"} & fields.keys():
        return "balance_sheet"
    if {"debit_total", "credit_total"} & fields.keys():
        return "trial_balance"
    if {"revenue", "cost_of_sales", "gross_profit"} & fields.keys():
        return "income_statement"
    return "invoice"


def build_document(text: str, entities: Entities) -> tuple[dict, dict]:
    """(raw document for intake, what was read and by whom).

    Cues decide first. The LLM is asked only when some written amount is still
    unassigned, and may only fill fields the cues left empty, with those amounts."""
    cue_fields = read_by_cues(text, entities.amounts)
    used = {v for v in cue_fields.values() if isinstance(v, float)}
    open_amounts = [a for a in entities.amounts if a.value not in used]
    llm_fields: dict = {}
    llm_doc_type, llm_error = None, None
    if (open_amounts or not cue_fields) and llm.available():
        try:
            proposed, llm_doc_type = read_by_llm(text, open_amounts)
            llm_fields = {k: v for k, v in proposed.items() if k not in cue_fields}
        except llm.LLMError as exc:
            llm_error = str(exc)
    fields = {**cue_fields, **llm_fields}
    source = {f: ("llm" if f in llm_fields else "cues") for f in fields}
    doc_type = llm_doc_type or _infer_doc_type(fields, entities)
    year = int(m.group(0)) if (m := _YEAR.search(text)) else datetime.now(UTC).year
    doc = {"doc_id": "WHATIF-1", "doc_type": doc_type, "period_year": year, "fields": fields,
           "confidences": {f: config.WHATIF_FIELD_CONFIDENCE for f in fields},
           "methods": {f: f"copilot_text:{source[f]}" for f in fields}}
    return doc, {"fields": fields, "read_by": source, "doc_type": doc_type,
                 "llm_error": llm_error}
