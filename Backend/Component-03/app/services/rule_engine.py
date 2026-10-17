"""Plain Python maths checks. No LLM here — fast and exact.
Every value-based finding carries structured claims so Validation can verify
the cited document's field really holds the claimed value (in code)."""
from app import config
from app.schemas.case import AuditCase, AuditDocument
from app.schemas.findings import EvidenceClaim, Finding
from app.services.expression import ExpressionError, evaluate


def _num(doc: AuditDocument, key: str) -> float | None:
    v = doc.fields.get(key)
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _conf(doc: AuditDocument, *fields: str) -> float:
    """Lowest OCR confidence among the source fields a finding is built on.
    1.0 when no confidence is known, so unknown never silently lowers trust."""
    vals = [float(doc.confidences[f]) for f in fields if f in doc.confidences]
    return min(vals) if vals else 1.0


def required_fields_for(doc_type: str) -> list[str]:
    return {"balance_sheet": ["assets", "liabilities", "capital"],
            "invoice": ["amount"]}.get(doc_type, [])


def rejected_doc_ids(case: AuditCase) -> list[str]:
    """Doc IDs missing a required field. Computed from fields, never from message text."""
    out = []
    for d in case.docs:
        if any(f not in d.fields or d.fields[f] is None for f in required_fields_for(d.doc_type)):
            out.append(d.doc_id)
    return out


def check_required_fields(doc: AuditDocument) -> list[Finding]:
    """CHK-006: required fields + format present."""
    required = required_fields_for(doc.doc_type)
    out: list[Finding] = []
    for f in required:
        if f not in doc.fields or doc.fields[f] is None:
            out.append(Finding(
                finding_id=f"{doc.doc_id}-CHK006-{f}", rule_id="CHK-006",
                category="format", severity="medium",
                message=f"Missing required field '{f}' in {doc.doc_id}.",
                evidence_ids=[doc.doc_id]))
    # Low OCR confidence is a review item, not an audit violation. Distinct
    # REV-001 id + review_status so UI and counts can separate the two.
    for fname, conf in doc.confidences.items():
        if conf < config.REVIEW_CONFIDENCE_LIMIT:
            out.append(Finding(
                finding_id=f"{doc.doc_id}-REV001-lowconf-{fname}", rule_id="REV-001",
                category="format", severity="low",
                message=f"Field '{fname}' has low confidence {conf:.2f}, needs human review (not an audit violation).",
                evidence_ids=[doc.doc_id], confidence=float(conf),
                review_status="needs_more_evidence"))
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
            evidence_ids=[doc.doc_id],
            confidence=_conf(doc, "assets", "liabilities", "capital"),
            claims=[EvidenceClaim(evidence_id=doc.doc_id, field="assets", claimed_value=a),
                    EvidenceClaim(evidence_id=doc.doc_id, field="liabilities", claimed_value=l),
                    EvidenceClaim(evidence_id=doc.doc_id, field="capital", claimed_value=c)])]
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
            evidence_ids=[doc.doc_id],
            confidence=_conf(doc, "debit_total", "credit_total"),
            claims=[EvidenceClaim(evidence_id=doc.doc_id, field="debit_total", claimed_value=d),
                    EvidenceClaim(evidence_id=doc.doc_id, field="credit_total", claimed_value=cr)])]
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
                evidence_ids=[d.doc_id, p.doc_id],
                confidence=min(_conf(d, "amount"), _conf(p, "amount")),
                claims=[EvidenceClaim(evidence_id=d.doc_id, field="amount", claimed_value=da),
                        EvidenceClaim(evidence_id=p.doc_id, field="amount", claimed_value=pa)]))
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
            cited = [d for d in case.docs if d.period_year in (prev, cur)]
            out.append(Finding(
                finding_id=f"{case.case_id}-CHK004-{cur}", rule_id="CHK-004",
                category="arithmetic", severity="medium",
                message=f"Big year jump: assets {totals[prev]:.0f} ({prev}) -> {totals[cur]:.0f} ({cur}), change {change:.0%}.",
                evidence_ids=[d.doc_id for d in cited],
                confidence=min((_conf(d, "assets") for d in cited), default=1.0)))
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
                evidence_ids=[d.doc_id],
                confidence=_conf(d, "cash_out", "purchase_basis"),
                claims=[EvidenceClaim(evidence_id=d.doc_id, field="cash_out", claimed_value=cash_out),
                        EvidenceClaim(evidence_id=d.doc_id, field="purchase_basis", claimed_value="credit")]))
    return out


def _attr(rule, key: str, default=None):
    return rule.get(key, default) if isinstance(rule, dict) else getattr(rule, key, default)


def run_check_rules(doc: AuditDocument, rules: list) -> list[Finding]:
    """Evaluate KG-supplied check rules for one document (data, not code).

    A rule with any missing/non-numeric input is skipped (Data Quality already
    flags missing fields). An unevaluable expression becomes a visible finding,
    never a silent skip."""
    out: list[Finding] = []
    for rule in rules:
        rule_id = _attr(rule, "rule_id", "")
        expr = _attr(rule, "expression", "")
        inputs = list(_attr(rule, "inputs", []) or [])
        tolerance = float(_attr(rule, "tolerance", config.AMOUNT_TOLERANCE) or 0.0)
        values: dict[str, float] = {}
        for name in inputs:
            v = doc.fields.get(name)
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                values = {}
                break
            values[name] = float(v)
        if not values and inputs:
            continue  # cannot compute without every input
        try:
            ok = evaluate(expr, values, tolerance)
        except ExpressionError as exc:
            out.append(Finding(
                finding_id=f"{doc.doc_id}-{rule_id}-expr", rule_id=rule_id,
                category=_attr(rule, "category", "format"),
                severity=_attr(rule, "severity", "medium"),
                message=f"Rule {rule_id} on {doc.doc_id} could not be evaluated: {exc}",
                evidence_ids=[doc.doc_id]))
            continue
        if not ok:
            name = _attr(rule, "name", "") or rule_id
            out.append(Finding(
                finding_id=f"{doc.doc_id}-{rule_id}", rule_id=rule_id,
                category=_attr(rule, "category", "format"),
                severity=_attr(rule, "severity", "medium"),
                message=f"{name} failed for {doc.doc_id}: {expr} is false.",
                evidence_ids=[doc.doc_id], policy_ids=[rule_id],
                confidence=min((_conf(doc, n) for n in inputs), default=1.0),
                claims=[EvidenceClaim(evidence_id=doc.doc_id, field=n, claimed_value=values[n])
                        for n in inputs]))
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
