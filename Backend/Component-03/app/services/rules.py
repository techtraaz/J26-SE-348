"""Plain-Python checks shared by the agents. No LLM here.

KG check rules are data: their expression is bound to document fields (using
the rule's `variables` for other names of the same line item) and evaluated by
app.services.expression. Every failed rule carries one claim per value it used,
so Evidence Validation can re-check each value against the document.

Rule ids: CHK-* and POL-* come from the KG. REV-* are C3 review items (never
violations):
  REV-001 low confidence field          REV-005 KG-linked evidence missing from case
  REV-002 unsupported document type     REV-006 KG rule could not be evaluated
  REV-003 unreadable/conflicting value  REV-007 KG rules could not be loaded
  REV-008 source not human-verified (C1 machine extraction)
  REV-004 intake issue (parent link, confidence range, no fields)
"""
from app import config
from app.schemas.case import AuditCase, AuditDocument
from app.schemas.findings import EvidenceClaim, Finding, TraceEntry
from app.schemas.kg import CheckRuleResponse, RuleResponse
from app.services import expression
from app.services.expression import ExpressionError

Value = float | str


def review(finding_id: str, rule_id: str, message: str, evidence_ids: list[str],
           confidence: float = 1.0, policy_ids: list[str] | None = None,
           severity: str = "low") -> Finding:
    """A review item: shown to the auditor, never counted as a violation."""
    return Finding(finding_id=finding_id, rule_id=rule_id, category="format",
                   severity=severity, message=message, evidence_ids=evidence_ids,
                   policy_ids=policy_ids or [], confidence=confidence,
                   review_status="needs_more_evidence")


def confidence_of(doc: AuditDocument, *keys: str) -> float:
    """Lowest known confidence among the fields used; 1.0 when none is known."""
    known = [float(doc.confidences[k]) for k in keys if k in doc.confidences]
    return min(known) if known else 1.0


def fmt(value: Value) -> str:
    return f"{value:,.2f}" if isinstance(value, float) else repr(value)


def _is_number(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def resolve(doc: AuditDocument, name: str,
            rule: CheckRuleResponse | None = None) -> tuple[str, object] | None:
    """Find a field by its name, its line-item code, or one of its aliases."""
    candidates = [name]
    if rule is not None:
        for v in rule.variables:
            if v.name == name:
                candidates += [v.line_item, *v.aliases]
    for key in candidates:
        if key and doc.fields.get(key) is not None:
            return key, doc.fields[key]
    return None


# --- KG check rules ----------------------------------------------------------

def rule_names(rule: CheckRuleResponse) -> list[str] | None:
    """Inputs of a rule, or None when its expression cannot be parsed."""
    try:
        return expression.names(rule.expression)
    except ExpressionError:
        return None


def is_anomaly_rule(rule: CheckRuleResponse) -> bool:
    """Cross-document / cross-year rules and fraud patterns go to Anomaly."""
    names = rule_names(rule) or []
    if any("." in n for n in names):
        return True
    return config.RULE_CATEGORY.get(rule.rule_id) == "possible_fraud"


def rules_for(rules: list[CheckRuleResponse], anomaly: bool) -> list[CheckRuleResponse]:
    return [r for r in rules
            if r.rule_id not in config.CODE_CHECKED_RULES and is_anomaly_rule(r) == anomaly]


def prior_doc(case: AuditCase, doc: AuditDocument) -> AuditDocument | str | None:
    """Same-type document of the closest earlier year. A string explains ambiguity."""
    earlier = [d for d in case.docs
               if d.doc_type == doc.doc_type and d.period_year < doc.period_year]
    if not earlier:
        return None
    year = max(d.period_year for d in earlier)
    same = [d for d in earlier if d.period_year == year]
    if len(same) > 1:
        return f"several {doc.doc_type} documents for {year}"
    return same[0]


def evaluate_rule(rule: CheckRuleResponse, doc: AuditDocument,
                  scopes: dict[str, AuditDocument] | None = None,
                  materiality: float | None = None) -> tuple[Finding | None, str | None]:
    """(finding, skip_reason). A passing rule returns (None, None).

    Plain names read `doc`; `prior.x`, `child.x`, `parent.x` read the document in
    `scopes`. A missing or unreadable input skips the rule with a reason. With a
    case materiality, a failure whose amount difference is below it stays a
    finding at low severity (never dropped); see below_materiality()."""
    names = rule_names(rule)
    if names is None:
        return _rule_error(rule, doc, "expression cannot be parsed"), None
    values: dict[str, Value] = {}
    sources: dict[str, tuple[AuditDocument, str]] = {}
    for name in names:
        scope, _, field = name.rpartition(".")
        target = (scopes or {}).get(scope) if scope else doc
        if target is None:
            return None, f"{rule.rule_id} on {doc.doc_id}: no {scope} document"
        hit = resolve(target, field, rule)
        if hit is None:
            return None, f"{rule.rule_id} on {doc.doc_id}: missing {name}"
        key, value = hit
        if key in config.NUMERIC_FIELDS and not _is_number(value):
            return None, f"{rule.rule_id} on {doc.doc_id}: {name} is not a number"
        if not (_is_number(value) or isinstance(value, str)):
            return None, f"{rule.rule_id} on {doc.doc_id}: {name} is not a value"
        values[name] = float(value) if _is_number(value) else value
        sources[name] = (target, key)
    try:
        ok = expression.evaluate(rule.expression, values, config.AMOUNT_TOLERANCE)
    except ExpressionError as exc:
        return _rule_error(rule, doc, str(exc)), None
    if ok:
        return None, None
    evidence_ids: list[str] = []
    for target, _ in sources.values():
        if target.doc_id not in evidence_ids:
            evidence_ids.append(target.doc_id)
    shown = ", ".join(f"{n}={fmt(v)}" for n, v in values.items())
    category = config.RULE_CATEGORY.get(rule.rule_id, config.DEFAULT_RULE_CATEGORY)
    severity, note = rule.severity, ""
    gap = below_materiality(rule, category, values, materiality)
    if gap is not None:
        severity = "low"
        note = (f" The difference {fmt(gap)} is below the case materiality {fmt(float(materiality))};"
                f" C2 rates this rule {rule.severity}.")
    return Finding(
        finding_id=f"{doc.doc_id}-{rule.rule_id}", rule_id=rule.rule_id,
        category=category, severity=severity,
        message=f"{rule.name or rule.rule_id} failed for {doc.doc_id}: "
                f"{rule.expression} is false ({shown}).{note}",
        evidence_ids=evidence_ids,
        confidence=min(confidence_of(t, k) for t, k in sources.values()) if sources else 1.0,
        claims=[EvidenceClaim(evidence_id=t.doc_id, field=k, claimed_value=values[n])
                for n, (t, k) in sources.items()]), None


def below_materiality(rule: CheckRuleResponse, category: str, values: dict[str, Value],
                      materiality: float | None) -> float | None:
    """The amount difference when it is below the case materiality, else None.
    Only plain amount comparisons qualify; fraud patterns are material whatever
    the amount (SLAuS 240), and ratios, thresholds and policy limits have no
    amount difference to compare."""
    if materiality is None or category == "possible_fraud":
        return None
    gap = expression.amount_difference(rule.expression, values)
    return gap if gap is not None and gap < materiality else None


def materiality_trace(agent: str, materiality: float | None, findings: list[Finding]) -> list[TraceEntry]:
    if materiality is None:
        return []
    below = sum("below the case materiality" in f.message for f in findings)
    return [TraceEntry(agent_name=agent, decision_type="materiality",
                       detail=f"Case materiality {fmt(float(materiality))}: {below} finding(s) below it "
                              f"kept at low severity (not dropped).")]


def _rule_error(rule: CheckRuleResponse, doc: AuditDocument, why: str) -> Finding:
    return review(f"{doc.doc_id}-REV006-{rule.rule_id}", "REV-006",
                  f"KG rule {rule.rule_id} could not be evaluated on {doc.doc_id}: {why}. "
                  f"Check it by hand.", [doc.doc_id], policy_ids=[rule.rule_id])


def policy_findings(doc: AuditDocument, rules: list[RuleResponse]) -> list[Finding]:
    """KG policy limits, e.g. POL-07: an amount above the limit needs the control
    (dual approval) confirmed. The approval itself is not in the evidence, so this
    asks the auditor to confirm it rather than claiming it is missing."""
    hit = resolve(doc, config.POLICY_LIMIT_FIELD)
    if hit is None or not _is_number(hit[1]):
        return []
    key, amount = hit[0], float(hit[1])
    out = []
    for r in rules:
        if r.limit is None or amount <= r.limit:
            continue
        out.append(Finding(
            finding_id=f"{doc.doc_id}-{r.rule_id}", rule_id=r.rule_id,
            category="compliance", severity="medium",
            message=f"{r.text} {doc.doc_id} has {key} {fmt(amount)} above the limit "
                    f"{fmt(float(r.limit))}; confirm the required approval.",
            evidence_ids=[doc.doc_id], policy_ids=[r.rule_id],
            confidence=confidence_of(doc, key),
            claims=[EvidenceClaim(evidence_id=doc.doc_id, field=key, claimed_value=amount)]))
    return out


# --- Data Quality checks -------------------------------------------------------

def missing_required(doc: AuditDocument) -> list[str]:
    """Required fields (CHK-006) with none of their accepted names filled."""
    need = config.REQUIRED_FIELDS.get(doc.doc_type, {})
    return [f for f, names in need.items()
            if all(doc.fields.get(n) is None for n in names)]


def data_quality_findings(case: AuditCase) -> list[Finding]:
    """Every data problem in the case, one finding per concern."""
    ids = {d.doc_id for d in case.docs}
    out: list[Finding] = []
    for d in case.docs:
        if d.doc_type == "unknown" or d.doc_type not in config.ALLOWED_DOC_TYPES:
            out.append(review(f"{d.doc_id}-REV002", "REV-002",
                              f"Unrecognised document {d.doc_id}: doc type '{d.doc_type}' "
                              f"is not supported, needs human review.", [d.doc_id]))
        for f in missing_required(d):
            out.append(Finding(
                finding_id=f"{d.doc_id}-CHK006-{f}", rule_id="CHK-006", category="format",
                severity="medium", message=f"Missing required field '{f}' in {d.doc_id}.",
                evidence_ids=[d.doc_id], policy_ids=["CHK-006"]))
        if not d.fields:
            out.append(review(f"{d.doc_id}-REV004-nofields", "REV-004",
                              f"No fields were extracted for {d.doc_id}; nothing on it "
                              f"could be checked.", [d.doc_id]))
        for fname, value in d.fields.items():
            if isinstance(value, list):
                out.append(review(f"{d.doc_id}-REV003-{fname}", "REV-003",
                                  f"Field '{fname}' in {d.doc_id} was read with conflicting "
                                  f"values {value!r}; needs human review.", [d.doc_id],
                                  confidence=confidence_of(d, fname)))
            elif fname in config.NUMERIC_FIELDS and value is not None and not _is_number(value):
                out.append(review(f"{d.doc_id}-REV003-{fname}", "REV-003",
                                  f"Field '{fname}' in {d.doc_id} holds {value!r}, which could "
                                  f"not be read as a number; needs human review.", [d.doc_id],
                                  confidence=confidence_of(d, fname)))
        for fname, conf in d.confidences.items():
            if not 0.0 <= conf <= 1.0:
                out.append(review(f"{d.doc_id}-REV004-conf-{fname}", "REV-004",
                                  f"Confidence {conf} for '{fname}' in {d.doc_id} is outside "
                                  f"0..1; the extraction score cannot be trusted.", [d.doc_id]))
            elif conf < config.REVIEW_CONFIDENCE_LIMIT:
                why = ("was matched to its line by AI and not confirmed by a person"
                       if d.methods.get(fname, "").endswith("c3:unconfirmed")
                       else f"has low confidence {conf:.2f}")
                out.append(review(f"{d.doc_id}-REV001-{fname}", "REV-001",
                                  f"Field '{fname}' in {d.doc_id} {why}; needs human review "
                                  f"(not an audit violation).", [d.doc_id], confidence=float(conf)))
        if d.parent_doc_id is not None and d.parent_doc_id not in ids:
            out.append(review(f"{d.doc_id}-REV004-parent", "REV-004",
                              f"{d.doc_id} says it supports {d.parent_doc_id}, which is not "
                              f"in this case.", [d.doc_id]))
        if d.source is not None and not d.source.human_verified:
            out.append(review(f"{d.doc_id}-REV008", "REV-008",
                              f"{d.doc_id} was read from {d.source.component.upper()}'s machine "
                              f"extraction; no person has verified it there yet.", [d.doc_id]))
    return out
