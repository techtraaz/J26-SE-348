"""Deterministic entity extraction from a Copilot request.

Only what is literally in the text is returned (IDs, rule ids, severities,
amounts...), so nothing here can be invented. The LLM is not used for this:
small models were measured inventing severities and mixing up IDs.
"""
import re
from dataclasses import dataclass, field

from app import config
from app.services.intake import parse_number

_RULE_ID = re.compile(r"\b(CHK|POL|REV)-?\s?(\d{1,3})\b", re.IGNORECASE)
_CASE_ID = re.compile(r"\bcase\s*(?:id|no\.?|number|#)?\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9_.-]{0,63})", re.IGNORECASE)
_VERSION = re.compile(r"\b(?:version|ver\.?|v)\s?(\d{1,4})\b", re.IGNORECASE)
_STANDARD = re.compile(r"\b(LKAS|SLFRS|SLAuS|CF)\s?(\d{1,4})?\b", re.IGNORECASE)
# Commas only as thousands groups; digits glued to letters or '-' (C-14, Q3) are IDs.
_AMOUNT = re.compile(r"(?:(?:rs|lkr)\.?\s*)?(?<![\w.-])\(?-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?"
                     r"(?:\s?(?:k|mn|m|million|thousand)\b)?", re.IGNORECASE)
_MULTIPLIER = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6}
_NOT_A_CASE = {"the", "this", "that", "my", "our", "a", "an", "of", "for", "in", "is", "it", "with"}

SEVERITY_WORDS = {"high": "high", "critical": "high", "severe": "high",
                  "medium": "medium", "moderate": "medium", "low": "low", "minor": "low"}
REVIEW_WORDS = {
    "needs_more_evidence": ("need review", "needs review", "needing review", "more evidence",
                            "needs_more_evidence", "low confidence", "uncertain"),
    "confirmed": ("confirmed",), "dismissed": ("dismissed",),
    "pending_review": ("pending",),
}
CATEGORY_WORDS = {"possible_fraud": ("fraud", "suspicious"), "ledger": ("ledger", "double entry"),
                  "arithmetic": ("arithmetic", "mismatch", "calculation"),
                  "compliance": ("compliance", "policy"), "format": ("format", "data quality")}
# Everyday names for C2 document types.
DOC_TYPE_SYNONYMS = {
    "bill": "invoice", "invoices": "invoice", "receipts": "receipt",
    "voucher": "payment_voucher", "vouchers": "payment_voucher",
    "ledger": "general_ledger", "gl": "general_ledger", "tb": "trial_balance",
    "p&l": "income_statement", "profit and loss": "income_statement",
    "statement of financial position": "balance_sheet", "sfp": "balance_sheet",
    "balance sheets": "balance_sheet", "cash flow": "cash_flow_statement",
    "payslip": "payroll", "salary": "payroll", "po": "purchase_order", "grn": "goods_received_note",
}


@dataclass
class Amount:
    value: float
    text: str


@dataclass
class Entities:
    case_ids: list[str] = field(default_factory=list)
    doc_ids: list[str] = field(default_factory=list)
    rule_ids: list[str] = field(default_factory=list)
    versions: list[int] = field(default_factory=list)
    severities: list[str] = field(default_factory=list)
    review_statuses: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    doc_types: list[str] = field(default_factory=list)
    standards: list[str] = field(default_factory=list)
    amounts: list[Amount] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: ([a.value for a in v] if k == "amounts" else v)
                for k, v in self.__dict__.items() if v}


def _words(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![a-z0-9_]){re.escape(phrase)}(?![a-z0-9_])", text) is not None


def _unique(values) -> list:
    return list(dict.fromkeys(values))


def amounts_in(text: str) -> list[Amount]:
    """Money-like numbers, e.g. 'Rs. 150,000', '1.2m', '(5,000)'. Years, versions
    and rule numbers are not money and are skipped."""
    out: list[Amount] = []
    skip_spans = [m.span() for p in (_RULE_ID, _VERSION, _STANDARD, _CASE_ID)
                  for m in p.finditer(text)]
    for m in _AMOUNT.finditer(text):
        if any(s <= m.start() < e for s, e in skip_spans):
            continue
        raw = m.group(0).strip()
        unit = re.search(r"(k|m|mn|million|thousand)$", raw, re.IGNORECASE)
        number_text = raw[:unit.start()].strip() if unit else raw
        value = parse_number(number_text)
        if not isinstance(value, float):
            continue
        has_money_mark = bool(re.match(r"(rs|lkr)", raw, re.IGNORECASE)) or "," in raw or unit
        if not has_money_mark and 1900 <= value <= 2999 and value.is_integer():
            continue  # a bare year
        if unit:
            value *= _MULTIPLIER[unit.group(1).lower()]
        out.append(Amount(value=value, text=raw))
    return out


def _looks_like_id(token: str) -> bool:
    """'CASE-12', 'abc_1', 'ACME' yes; 'the', 'status' no."""
    if token.lower() in _NOT_A_CASE:
        return False
    return any(ch.isdigit() or ch in "-_." for ch in token) or (token.isupper() and len(token) > 1)


def _rule_id(prefix: str, number: str) -> str:
    prefix = prefix.upper()
    return f"POL-{int(number):02d}" if prefix == "POL" else f"{prefix}-{int(number):03d}"


def extract(text: str, known_doc_ids: list[str] | None = None,
            known_case_ids: list[str] | None = None) -> Entities:
    low = text.lower()
    ent = Entities()
    ent.rule_ids = _unique(_rule_id(a, n) for a, n in _RULE_ID.findall(text))
    named = [c.rstrip(".") for c in _CASE_ID.findall(text) if _looks_like_id(c.rstrip("."))]
    known = [c for c in (known_case_ids or []) if _words(low, c.lower())]
    ent.case_ids = _unique(named + known)
    ent.versions = _unique(int(v) for v in _VERSION.findall(text))
    ent.standards = _unique(f"{s.upper() if s.upper() != 'SLAUS' else 'SLAuS'}"
                            f"{' ' + n if n else ''}" for s, n in _STANDARD.findall(text))
    ent.severities = _unique(v for k, v in SEVERITY_WORDS.items() if _words(low, k))
    ent.review_statuses = _unique(s for s, words in REVIEW_WORDS.items()
                                  if any(w in low for w in words))
    ent.categories = _unique(c for c, words in CATEGORY_WORDS.items()
                             if any(_words(low, w) for w in words))
    types = [t for t in config.ALLOWED_DOC_TYPES
             if t != "unknown" and (_words(low, t) or _words(low, t.replace("_", " ")))]
    types += [t for word, t in DOC_TYPE_SYNONYMS.items()
              if _words(low, word) or _words(low, word + "s")]
    types += [t for t in config.ALLOWED_DOC_TYPES if _words(low, t.replace("_", " ") + "s")]
    ent.doc_types = _unique(types)
    if known_doc_ids:
        ent.doc_ids = [d for d in known_doc_ids if _words(low, d.lower())]
    ent.amounts = amounts_in(text)
    return ent
