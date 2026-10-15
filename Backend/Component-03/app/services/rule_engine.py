"""Plain Python maths checks. No LLM here — fast and exact."""
from app import config
from app.schemas.case import AuditCase, AuditDocument
from app.schemas.findings import Finding


def _num(doc: AuditDocument, key: str) -> float | None:
    v = doc.fields.get(key)
    if isinstance(v, (int, float)):
        return float(v)
    return None


def check_required_fields(doc: AuditDocument) -> list[Finding]:
    """CHK-006: required fields + format present."""
    required = {"balance_sheet": ["assets", "liabilities", "capital"],
                "invoice": ["amount"]}.get(doc.doc_type, [])
    out: list[Finding] = []
    for f in required:
        if f not in doc.fields or doc.fields[f] is None:
            out.append(Finding(
                finding_id=f"{doc.doc_id}-CHK006-{f}", rule_id="CHK-006",
                category="format", severity="medium",
                message=f"Missing required field '{f}' in {doc.doc_id}.",
                evidence_ids=[doc.doc_id]))
    # low OCR confidence flag
    for fname, conf in doc.confidences.items():
        if conf < 0.5:
            out.append(Finding(
                finding_id=f"{doc.doc_id}-CHK006-lowconf-{fname}", rule_id="CHK-006",
                category="format", severity="low",
                message=f"Field '{fname}' has low confidence {conf:.2f}, needs human review.",
                evidence_ids=[doc.doc_id], confidence=float(conf)))
    return out


def check_accounting_equation(doc: AuditDocument) -> list[Finding]:
    """CHK-001: assets == liabilities + capital."""
    a, l, c = _num(doc, "assets"), _num(doc, "liabilities"), _num(doc, "capital")
    if a is None or l is None or c is None:
        return []
    if abs(a - (l + c)) > config.AMOUNT_TOLERANCE:
        return [Finding(
            finding_id=f"{doc.doc_id}-CHK001", rule_id="CHK-001",
            category="ledger", severity="high",
            message=f"Equation broken in {doc.doc_id}: assets {a} != liabilities {l} + capital {c}.",
            evidence_ids=[doc.doc_id])]
    return []


def check_debit_credit(doc: AuditDocument) -> list[Finding]:
    """CHK-002: sum(debit) == sum(credit)."""
    d, cr = _num(doc, "debit_total"), _num(doc, "credit_total")
    if d is None or cr is None:
        return []
    if abs(d - cr) > config.AMOUNT_TOLERANCE:
        return [Finding(
            finding_id=f"{doc.doc_id}-CHK002", rule_id="CHK-002",
            category="ledger", severity="high",
            message=f"Debit {d} != credit {cr} in {doc.doc_id}. Wrong side or wrong account (e.g. TV as liability).",
            evidence_ids=[doc.doc_id])]
    return []


def check_parent_amount_match(case: AuditCase) -> list[Finding]:
    """CHK-003: child amount must match parent amount."""
    by_id = {d.doc_id: d for d in case.docs}
    out: list[Finding] = []
    for d in case.docs:
        if not d.parent_doc_id or d.parent_doc_id not in by_id:
            continue
        p = by_id[d.parent_doc_id]
        da, pa = _num(d, "amount"), _num(p, "amount")
        if da is not None and pa is not None and abs(da - pa) > config.AMOUNT_TOLERANCE:
            out.append(Finding(
                finding_id=f"{d.doc_id}-CHK003", rule_id="CHK-003",
                category="arithmetic", severity="high",
                message=f"Amount mismatch: {d.doc_id} has {da} but parent {p.doc_id} has {pa}.",
                evidence_ids=[d.doc_id, p.doc_id]))
    return out


def check_year_change(case: AuditCase) -> list[Finding]:
    """CHK-004: this year vs last year jump bigger than limit."""
    totals: dict[int, float] = {}
    for d in case.docs:
        if d.doc_type == "balance_sheet":
            a = _num(d, "assets")
            if a is not None:
                totals[d.period_year] = totals.get(d.period_year, 0.0) + a
    out: list[Finding] = []
    years = sorted(totals)
    for i in range(1, len(years)):
        prev, cur = years[i - 1], years[i]
        if totals[prev] == 0:
            continue
        change = abs(totals[cur] - totals[prev]) / abs(totals[prev])
        if change > config.YEAR_CHANGE_LIMIT:
            out.append(Finding(
                finding_id=f"{case.case_id}-CHK004-{cur}", rule_id="CHK-004",
                category="arithmetic", severity="medium",
                message=f"Big year jump: assets {totals[prev]:.0f} ({prev}) -> {totals[cur]:.0f} ({cur}), change {change:.0%}.",
                evidence_ids=[d.doc_id for d in case.docs if d.period_year in (prev, cur)]))
    return out


def check_cash_without_asset(case: AuditCase) -> list[Finding]:
    """CHK-005: cash went out but purchase booked on credit (possible fraud pattern)."""
    out: list[Finding] = []
    for d in case.docs:
        cash_out = _num(d, "cash_out")
        booked = str(d.fields.get("purchase_basis", "cash")).lower()
        asset_in = _num(d, "asset_in")
        if cash_out is not None and cash_out > 0 and booked == "credit" and (asset_in is None or asset_in == 0):
            out.append(Finding(
                finding_id=f"{d.doc_id}-CHK005", rule_id="CHK-005",
                category="possible_fraud", severity="high",
                message=f"Cash {cash_out:.0f} left in {d.doc_id} but purchase booked as credit with no asset in. Needs auditor review.",
                evidence_ids=[d.doc_id]))
    return out


def run_all_code_checks(case: AuditCase) -> list[Finding]:
    out: list[Finding] = []
    for d in case.docs:
        out += check_required_fields(d)
        out += check_accounting_equation(d)
        out += check_debit_credit(d)
    out += check_parent_amount_match(case)
    out += check_year_change(case)
    out += check_cash_without_asset(case)
    return out
