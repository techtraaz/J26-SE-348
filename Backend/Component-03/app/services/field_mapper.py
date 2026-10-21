"""Turn Component-01's lines into document fields. C1 reads lines, not fields,
and documents follow no template, so C3 finds label -> value pairs itself.

1. Rules (always): a label and its amount on one line ("Total Amount Rs. 125,000"),
   a label with the amount to its right on the same row (by box), or a label
   with the amount on the next line. Labels are matched against Component-02's
   field names and aliases (/query/fields) plus everyday receipt wording.
2. LLM (only when needed): when a field the document's rules need is still
   missing and some lines holding numbers are unused. The LLM picks LINE IDS for
   the missing fields; the value is then read from that line in code, so a
   number can never be invented.
3. Suggestions: document type from keywords, year from dates. Only suggestions:
   the reviewer confirms them.

Nothing here decides a verdict; it only says which line holds which value.
"""
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from pydantic import create_model

from app import config
from app.schemas.c1 import C1Extraction, C1VerifiedRecord
from app.schemas.case import DocumentSource
from app.services import llm
from app.services.intake import parse_number
from app.services.kg_client import KGClient, KGError
from app.services.rules import rule_names

# Everyday labels for the fields C3's own checks use (C2 has no line item for them).
EVERYDAY_LABELS: dict[str, str] = {
    "total": "amount", "grand total": "amount", "total amount": "amount", "amount": "amount",
    "amount due": "amount", "total due": "amount", "net amount": "amount", "net total": "amount",
    "amount payable": "amount", "total payable": "amount", "invoice total": "amount",
    "invoice amount": "amount", "balance due": "amount", "amount paid": "amount",
    "total paid": "amount", "bill amount": "amount", "receipt amount": "amount",
    "cash paid": "cash_out", "cash out": "cash_out", "cash payment": "cash_out",
    "paid in cash": "cash_out",
    "payment method": "purchase_basis", "payment mode": "purchase_basis",
    "mode of payment": "purchase_basis", "payment terms": "purchase_basis",
    "payment type": "purchase_basis", "purchase basis": "purchase_basis", "terms": "purchase_basis",
}
TEXT_FIELDS: dict[str, tuple[str, ...]] = {
    "purchase_basis": ("credit", "cash", "card", "cheque", "bank transfer"),
}
# Longest phrase first, so "statement of financial position" beats "statement".
DOC_TYPE_KEYWORDS: tuple[tuple[str, str], ...] = tuple(sorted({
    "statement of financial position": "balance_sheet", "balance sheet": "balance_sheet",
    "statement of profit or loss": "income_statement", "income statement": "income_statement",
    "profit and loss": "income_statement", "statement of cash flows": "cash_flow_statement",
    "cash flow statement": "cash_flow_statement", "statement of changes in equity": "equity_statement",
    "trial balance": "trial_balance", "general ledger": "general_ledger",
    "tax invoice": "invoice", "invoice": "invoice", "receipt": "receipt",
    "payment voucher": "payment_voucher", "bank statement": "bank_statement",
    "purchase order": "purchase_order", "goods received note": "goods_received_note",
    "fixed asset register": "fixed_asset_register", "payroll": "payroll", "salary sheet": "payroll",
}.items(), key=lambda kv: -len(kv[0])))

_DATES = re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}:\d{2}(:\d{2})?\b")
# Digits glued to letters, '.', '/' or '-' are ids or dates, not money ("INV-00123", "No.45").
_AMOUNT = re.compile(r"(?<![\w./-])(?:(?:rs|lkr)\.?\s*)?\(?-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?(?:\s*/-)?",
                     re.IGNORECASE)
_BARE_YEAR = re.compile(r"^(19[5-9]\d|20\d{2}|2100)$")
_YEAR = re.compile(r"\b(19[5-9]\d|20\d{2}|2100)\b")
_YEAR_ENDED = re.compile(r"\b(year|period)\s+ended\b", re.IGNORECASE)
_CREDIT = re.compile(r"\b(on|as) credit\b|\bcredit (purchase|sale)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Line:
    line_id: str  # "p<page>#<sequence>"
    page: int
    sequence: int
    text: str
    confidence: float | None  # raw engine score
    box: tuple[int, int, int, int] | None
    provenance: str
    verified: bool  # a person confirmed this line in C1


@dataclass
class MappedField:
    field: str
    value: float | str
    line_id: str
    method: Literal["rules", "llm"]
    label: str = ""
    label_line_id: str | None = None  # when the label sits on another line
    specificity: int = 0
    alternatives: list[dict] = field(default_factory=list)


@dataclass
class ApprovalRow:
    label: str  # e.g. "Approval 2 - Director"
    signed: bool  # a signing date is filled in
    line_ids: list[str]  # the label and the lines under it


@dataclass
class Suggestion:
    value: str | int
    evidence: str
    line_id: str


@dataclass
class Mapping:
    fields: dict[str, MappedField]
    doc_type: Suggestion | None
    period_year: Suggestion | None
    unmapped: list[Line]
    missing: list[str]  # required fields not found
    llm_used: bool = False
    llm_error: str | None = None
    rules_not_runnable: list[dict] = field(default_factory=list)  # optional inputs absent


# --- reading C1 records ------------------------------------------------------

def _box(raw: list[int] | None) -> tuple[int, int, int, int] | None:
    return tuple(raw[:4]) if raw and len(raw) >= 4 else None  # type: ignore[return-value]


def read_record(extraction: C1Extraction | None,
                verified: C1VerifiedRecord | None) -> tuple[list[Line], DocumentSource]:
    """Lines plus where they came from. A verified record always wins."""
    if verified is not None:
        lines = [Line(line_id=ln.line_id, page=ln.page, sequence=ln.sequence, text=ln.text,
                      confidence=ln.confidence, box=_box(ln.box), provenance=ln.provenance,
                      verified=True) for ln in verified.lines]
        source = DocumentSource(document_id=verified.document_id, run_id=verified.based_on_run_id,
                                verified_version=verified.version, confirmed_by=verified.confirmed_by)
    elif extraction is not None:
        lines = [Line(line_id=f"p{r.page_number}#{r.sequence}", page=r.page_number,
                      sequence=r.sequence, text=r.text, confidence=r.confidence, box=_box(r.box),
                      provenance=r.provenance, verified=False) for r in extraction.regions]
        source = DocumentSource(document_id=extraction.document_id, run_id=extraction.run.id)
    else:
        raise ValueError("a C1 extraction or verified record is required")
    return sorted(lines, key=lambda ln: (ln.page, ln.sequence)), source


# --- labels and values ---------------------------------------------------------

def norm(label: str) -> str:
    text = label.lower().replace("&", " and ").replace("_", " ")
    text = re.sub(r"\b(rs|lkr)\b\.?", " ", text)
    text = re.sub(r"[^a-z ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def lexicon(field_map: dict[str, str]) -> dict[str, str]:
    """Normalized label -> field name: C2's line items and aliases, then everyday wording."""
    lex = {norm(name): code for name, code in field_map.items()}
    lex.update({norm(k): v for k, v in EVERYDAY_LABELS.items()})
    return {k: v for k, v in lex.items() if k}


def _match_label(label: str, lex: dict[str, str]) -> tuple[str, str, int] | None:
    """(field, matched label, words matched). Tries the whole label, then its
    endings ("net amount payable" -> "amount payable")."""
    words = norm(label).split()
    for start in range(len(words)):
        key = " ".join(words[start:])
        if key in lex:
            return lex[key], key, len(words) - start
    return None


def _amounts(text: str) -> list[tuple[float, int, int]]:
    """(value, start, end) of money-like numbers; dates and times are not money."""
    masked = _DATES.sub(lambda m: " " * len(m.group(0)), text)
    out = []
    for m in _AMOUNT.finditer(masked):
        raw = m.group(0).strip().removesuffix("/-").strip()
        if _BARE_YEAR.match(raw):
            continue  # a column heading such as "2026  2025", not an amount
        value = parse_number(raw)
        if isinstance(value, float):
            out.append((value, m.start(), m.end()))
    return out


def first_amount(text: str) -> float | None:
    found = _amounts(text)
    return found[0][0] if found else None


def text_value(field_name: str, text: str) -> str | None:
    low = text.lower()
    return next((v for v in TEXT_FIELDS.get(field_name, ()) if re.search(rf"\b{v}\b", low)), None)


def _same_row(a: Line, b: Line) -> bool:
    if not (a.box and b.box) or a.page != b.page:
        return False
    top, bottom = max(a.box[1], b.box[1]), min(a.box[3], b.box[3])
    shorter = min(a.box[3] - a.box[1], b.box[3] - b.box[1]) or 1
    return (bottom - top) / shorter >= 0.5 and b.box[0] >= a.box[0]


def _is_note_ref(text: str, next_text: str) -> bool:
    """A 'Note' column reference such as the 7 in 'Inventories 7 7,015,300': a bare
    number of up to three digits followed on its row by a money-formatted amount."""
    bare = text.strip()
    return bare.isdigit() and len(bare) <= 3 and any(c in next_text for c in ",.")


def _is_pure_value(line: Line) -> float | None:
    found = _amounts(line.text)
    if len(found) != 1:
        return None
    value, start, end = found[0]
    rest = norm(line.text[:start] + line.text[end:])
    return value if not rest else None


# --- the rules -------------------------------------------------------------------

def map_by_rules(lines: list[Line], lex: dict[str, str]) -> dict[str, MappedField]:
    candidates: dict[str, list[MappedField]] = {}

    def add(mf: MappedField) -> None:
        candidates.setdefault(mf.field, []).append(mf)

    for i, line in enumerate(lines):
        found = _amounts(line.text)
        label_text = line.text[:found[0][1]] if found else line.text
        if ":" in label_text:
            label_text = label_text.split(":", 1)[0]
        hit = _match_label(label_text, lex)
        if hit is None:
            continue
        name, label, specificity = hit
        if name in TEXT_FIELDS:
            value = text_value(name, line.text[len(label_text):])
            if value:
                add(MappedField(name, value, line.line_id, "rules", label, None, specificity))
            continue
        if found:  # label and amount on one line; the first amount is the current period
            first = found[0]
            if len(found) > 1 and _is_note_ref(line.text[first[1]:first[2]],
                                               line.text[found[1][1]:found[1][2]]):
                first = found[1]
            add(MappedField(name, first[0], line.line_id, "rules", label, None, specificity))
            continue
        partner = _value_partner(line, lines, i)
        if partner is not None:
            value = _is_pure_value(partner)
            add(MappedField(name, value, partner.line_id, "rules", label, line.line_id, specificity))

    out: dict[str, MappedField] = {}
    for name, cands in candidates.items():
        # Most specific label wins; on a tie the later line (totals sit at the bottom).
        best = max(cands, key=lambda c: (c.specificity, lines.index(_by_id(lines, c.line_id))))
        best.alternatives = [{"value": c.value, "line_id": c.line_id} for c in cands
                             if c is not best and c.value != best.value]
        out[name] = best
    if "purchase_basis" not in out:
        for line in lines:
            if _CREDIT.search(line.text):
                out["purchase_basis"] = MappedField("purchase_basis", "credit", line.line_id,
                                                    "rules", "on credit", None, 1)
                break
    rows = read_approvals(lines)
    if rows:
        signed = sum(r.signed for r in rows)
        summary = "; ".join(f"{r.label} ({'signed' if r.signed else 'blank'})" for r in rows)
        out[APPROVALS_FIELD] = MappedField(APPROVALS_FIELD, float(signed), rows[0].line_ids[0],
                                           "rules", summary, None, 1)
    return out


# --- approval stamps ---------------------------------------------------------------

APPROVALS_FIELD = config.APPROVALS_FIELD  # number of approval rows that are signed (dated)
# A stamp row starts a line: "Approval 1 - Finance", "Approved by", "Verified (Accounts)".
_APPROVAL_ROW = re.compile(r"^\W*approv(?:al|ed)\b", re.IGNORECASE)
_STAMP_ROW = re.compile(r"^\W*(approv(?:al|ed)|verified|prepared|checked|reviewed)\b", re.IGNORECASE)
_SIGNED_DATE = re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b")
APPROVAL_ROW_LINES = 8  # without boxes: header cells, name, designation and date as lines
APPROVAL_REACH = 10  # with boxes: a stamp row reaches this many label heights down


def _stamp_area(label: Line, lines: list[Line], stamps: list[Line]) -> list[Line]:
    """Lines inside a stamp label's area: right of the label up to the next stamp
    label on its row (sign-off columns), and down to the next stamp label under it
    (stamp rows), at most APPROVAL_REACH label heights."""
    x0, top, _, bottom = label.box  # type: ignore[misc]
    height = (bottom - top) or 1
    same_page = [s for s in stamps if s is not label and s.page == label.page and s.box]
    right = min((s.box[0] for s in same_page if _same_row(label, s)), default=float("inf"))
    under = [s.box[1] - (s.box[3] - s.box[1]) / 2 for s in same_page
             if s.box[1] >= bottom and s.box[0] < right and s.box[2] > x0 - height]
    end = min([top + APPROVAL_REACH * height, *under])
    return [ln for ln in lines if ln is not label and ln.page == label.page and ln.box
            and top - height / 2 <= ln.box[1] < end and x0 - height <= ln.box[0] < right]


def read_approvals(lines: list[Line]) -> list[ApprovalRow]:
    """The approval rows of an authorisation stamp or sign-off block. A row counts
    as signed when a date is filled in for it (the signature itself is an image,
    not text). A row ends at the next stamp row, so a blank row never borrows the
    next one's date. Lines without boxes are read in order instead."""
    stamps = [ln for ln in lines if _STAMP_ROW.search(ln.text)]
    rows = []
    for i, line in enumerate(lines):
        if not _APPROVAL_ROW.search(line.text):
            continue
        if line.box:
            area = _stamp_area(line, lines, stamps)
        else:
            area = []
            for nxt in lines[i + 1:i + 1 + APPROVAL_ROW_LINES]:
                if nxt.page != line.page or _STAMP_ROW.search(nxt.text):
                    break
                area.append(nxt)
        dated = [ln for ln in [line, *area] if _SIGNED_DATE.search(ln.text)]
        label = re.split(r"\b(name|designation|signature|date)\b", line.text, maxsplit=1,
                         flags=re.IGNORECASE)[0].strip(" -:/")
        rows.append(ApprovalRow(label or line.text.strip(), bool(dated),
                                [line.line_id, *(d.line_id for d in dated if d is not line)]))
    return rows


def _by_id(lines: list[Line], line_id: str) -> Line:
    return next(ln for ln in lines if ln.line_id == line_id)


def _value_partner(label: Line, lines: list[Line], index: int) -> Line | None:
    """The amount for a label-only line: to its right on the same row, else the next line."""
    row = [ln for ln in lines if ln is not label and _same_row(label, ln) and _is_pure_value(ln) is not None]
    row.sort(key=lambda ln: ln.box[0] - label.box[2])  # type: ignore[index]
    if len(row) > 1 and _is_note_ref(row[0].text, row[1].text):
        row = row[1:]
    if row:
        return row[0]
    nxt = lines[index + 1] if index + 1 < len(lines) else None
    below = nxt is not None and nxt.page == label.page and _is_pure_value(nxt) is not None
    lined_up = below and (not (label.box and nxt.box)
                          or (nxt.box[0] < label.box[2] and nxt.box[2] > label.box[0]))
    return nxt if lined_up else None


# --- suggestions -------------------------------------------------------------------

def suggest_doc_type(lines: list[Line]) -> Suggestion | None:
    for line in lines[:40]:  # titles sit near the top
        low = f" {norm(line.text)} "
        for phrase, doc_type in DOC_TYPE_KEYWORDS:
            if f" {phrase} " in low:
                return Suggestion(doc_type, line.text.strip(), line.line_id)
    return None


def suggest_year(lines: list[Line]) -> Suggestion | None:
    """'for the year ended 31 March 2026' first, else the most common four-digit
    year in the document. Two-digit years are never turned into a suggestion."""
    for line in lines:
        if _YEAR_ENDED.search(line.text) and (m := _YEAR.search(line.text)):
            return Suggestion(int(m.group(0)), line.text.strip(), line.line_id)
    seen = [(int(m.group(0)), line) for line in lines for m in _YEAR.finditer(line.text)]
    if not seen:
        return None
    year, _ = Counter(y for y, _ in seen).most_common(1)[0]
    line = next(ln for y, ln in seen if y == year)
    return Suggestion(year, line.text.strip(), line.line_id)


# --- what the document's rules need ----------------------------------------------

def required_fields(doc_type: str, kg: KGClient) -> list[list[str]]:
    """Fields the document cannot be audited without: CHK-006's required fields and
    the policy-limit field when the KG has a limit for this type. Each group lists
    the names (field and aliases) any one of which satisfies it."""
    groups = [list(names) for names in config.REQUIRED_FIELDS.get(doc_type, {}).values()]
    try:
        if kg.get_rules(doc_type):
            groups.append([config.POLICY_LIMIT_FIELD])
    except (ValueError, KGError):
        pass
    return _dedupe(groups)


def rule_inputs(doc_type: str, kg: KGClient) -> list[tuple[str, list[list[str]]]]:
    """(rule_id, input groups) of the KG check rules for the type. An absent input
    only means that rule does not apply; it is reported, never guessed."""
    try:
        rules = kg.get_check_rules(doc_type)
    except (ValueError, KGError):
        return []
    out = []
    for rule in rules:
        if rule.rule_id in config.CODE_CHECKED_RULES:
            continue
        variables = {v.name: v for v in rule.variables}
        groups = []
        for name in rule_names(rule) or []:
            base = name.rpartition(".")[2]
            v = variables.get(base)
            groups.append([base, *([v.line_item, *v.aliases] if v else [])])
        out.append((rule.rule_id, _dedupe(groups)))
    return out


def _dedupe(groups: list[list[str]]) -> list[list[str]]:
    out: list[list[str]] = []
    for group in groups:
        names = list(dict.fromkeys(n for n in group if n))
        if names and names not in out:
            out.append(names)
    return out


def target_name(group: list[str], field_map: dict[str, str]) -> str:
    """The name to store a missing field under: the C2 line item when there is one."""
    return field_map.get(group[0], group[0])


# --- the LLM fallback ----------------------------------------------------------------

MAX_LLM_LINES = 150


def map_by_llm(lines: list[Line], missing: list[str], open_lines: list[Line],
               doc_type: str) -> dict[str, MappedField]:
    """Ask the LLM which open line holds each missing field. Raises llm.LLMError."""
    ids = tuple(ln.line_id for ln in open_lines)
    pick = create_model("Pick", field=(Literal[tuple(missing)], ...),  # type: ignore[valid-type]
                        line_id=(Literal[ids], ...))  # type: ignore[valid-type]
    picks = create_model("Picks", picks=(list[pick], ...))  # type: ignore[valid-type]
    shown = "\n".join(f"{ln.line_id}: {ln.text[:120]}" for ln in lines[:MAX_LLM_LINES])
    out = llm.complete_json(
        "You match the lines of a financial document to accounting fields. For each wanted "
        "field, give the id of the line that holds its amount, only when you are sure. Use only "
        "line ids from the list; skip a field rather than guess.",
        f"Document type: {doc_type}.\nWanted fields: {', '.join(missing)}.\n"
        f"Lines that may hold them: {', '.join(ids)}.\nAll lines:\n{shown}", picks)
    by_id = {ln.line_id: ln for ln in open_lines}
    result: dict[str, MappedField] = {}
    used: set[str] = set()
    for p in out.picks:
        if p.field in result or p.line_id in used:
            continue  # one line per field, one field per line
        value = first_amount(by_id[p.line_id].text)
        if value is None:
            continue
        result[p.field] = MappedField(p.field, value, p.line_id, "llm")
        used.add(p.line_id)
    return result


def _satisfied(group: list[str], fields: dict[str, MappedField]) -> bool:
    return any(n in fields for n in group)


def map_document(lines: list[Line], doc_type: str | None, kg: KGClient,
                 use_llm: bool = True) -> Mapping:
    field_map = kg.get_field_map()
    fields = map_by_rules(lines, lexicon(field_map))
    doc_suggestion = suggest_doc_type(lines)
    effective_type = doc_type or (str(doc_suggestion.value) if doc_suggestion else "unknown")
    missing = list(dict.fromkeys(target_name(g, field_map)
                                 for g in required_fields(effective_type, kg) if not _satisfied(g, fields)))
    used = {f.line_id for f in fields.values()} | {f.label_line_id for f in fields.values() if f.label_line_id}
    open_lines = [ln for ln in lines if ln.line_id not in used and first_amount(ln.text) is not None]
    mapping = Mapping(fields, doc_suggestion, suggest_year(lines), open_lines, missing)
    # Only required fields go to the LLM: an optional rule input that is absent
    # (e.g. no "cash out" on an invoice) must not be filled with a guessed line.
    if use_llm and missing and open_lines and llm.available():
        try:
            picked = map_by_llm(lines, missing, open_lines, effective_type)
        except llm.LLMError as exc:
            mapping.llm_error = str(exc)
        else:
            mapping.llm_used = True
            fields.update(picked)
            taken = {f.line_id for f in picked.values()}
            mapping.unmapped = [ln for ln in open_lines if ln.line_id not in taken]
            mapping.missing = [m for m in missing if m not in picked]
    mapping.rules_not_runnable = [
        {"rule_id": rule_id, "missing": [target_name(g, field_map) for g in groups if not _satisfied(g, fields)]}
        for rule_id, groups in rule_inputs(effective_type, kg)
        if any(not _satisfied(g, fields) for g in groups)]
    return mapping
