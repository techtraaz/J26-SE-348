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
import re

from app import config
from app.schemas.case import AuditCase, AuditDocument
from app.schemas.findings import EvidenceClaim, Finding, RuleApplication, TraceEntry
from app.schemas.kg import CheckRuleResponse, RuleResponse
from app.services import expression, xai_trace
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


def label(doc: AuditDocument) -> str:
    """How a document is named to people: its file name when known, else its id."""
    return doc.name or doc.doc_id


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
    """(finding, skip_reason). A passing rule returns (None, None)."""
    finding, skip, _ = check_rule(rule, doc, scopes, materiality)
    return finding, skip


def calculation(sides: dict | None) -> str:
    """Both sides worked out in words, e.g. 'assets 164,673,550.00 vs liabilities
    + capital 152,611,400.00'; empty when the rule is not one comparison."""
    if not sides:
        return ""
    def show(v) -> str:
        return fmt(float(v)) if _is_number(v) else repr(v)
    return f"{sides['left']} {show(sides['left_value'])} vs {sides['right']} {show(sides['right_value'])}"


def emit(applied: RuleApplication) -> None:
    """The live XAI step for one rule application (a no-op outside a traced run)."""
    if applied.kind == "policy_check":
        field, amount = next(iter(applied.values.items()), (config.POLICY_LIMIT_FIELD, None))
        xai_trace.step("policy_check", applied.outcome, rule_id=applied.rule_id, text=applied.rule_name,
                       doc_id=applied.doc_id, doc_type=applied.doc_type, field=field, amount=amount,
                       limit=applied.limit, approvals_required=applied.approvals_required,
                       approvals_signed=applied.approvals_signed)
        return
    xai_trace.step("rule_check", applied.outcome, rule_id=applied.rule_id, rule_name=applied.rule_name,
                   expression=applied.expression, doc_id=applied.doc_id, doc_type=applied.doc_type,
                   compared_with=applied.compared_with, values=applied.values, sides=applied.sides,
                   severity=applied.severity, below_materiality=applied.below_materiality,
                   reason=applied.reason)


def skipped_rule(rule: CheckRuleResponse, doc: AuditDocument, reason: str,
                 agent: str = "compliance") -> RuleApplication:
    """A rule not run on a document (e.g. no single prior-year document), recorded and traced."""
    applied = RuleApplication(rule_id=rule.rule_id, rule_name=rule.name, doc_id=doc.doc_id,
                              doc_type=doc.doc_type, agent=agent, outcome="skipped",
                              expression=rule.expression, severity=rule.severity, reason=reason)
    emit(applied)
    return applied


def check_rule(rule: CheckRuleResponse, doc: AuditDocument,
               scopes: dict[str, AuditDocument] | None = None,
               materiality: float | None = None,
               agent: str = "compliance") -> tuple[Finding | None, str | None, RuleApplication]:
    """(finding, skip_reason, what happened). A passing rule has no finding and no
    skip reason; its RuleApplication still records the values and both sides.

    Plain names read `doc`; `prior.x`, `child.x`, `parent.x` read the document in
    `scopes`. A missing or unreadable input skips the rule with a reason. With a
    case materiality, a failure whose amount difference is below it stays a
    finding at low severity (never dropped); see below_materiality().
    Every check is also sent as an XAI rule_check step with the same facts."""
    values: dict[str, Value] = {}

    def done(outcome, finding: Finding | None = None, skip: str | None = None, reason: str | None = None):
        sides = expression.sides(rule.expression, values) if values else None
        applied = RuleApplication(
            rule_id=rule.rule_id, rule_name=rule.name, doc_id=doc.doc_id, doc_type=doc.doc_type,
            agent=agent, outcome=outcome, expression=rule.expression, values=dict(values),
            sides=sides, compared_with={k: v.doc_id for k, v in (scopes or {}).items()},
            severity=finding.severity if finding is not None else rule.severity,
            below_materiality=bool(finding and "below the case materiality" in finding.message),
            reason=reason, detail=calculation(sides),
            finding_id=finding.finding_id if finding is not None else None)
        emit(applied)
        return finding, skip, applied

    def skipped(why: str):
        return done("skipped", skip=f"{rule.rule_id} on {doc.doc_id}: {why}", reason=why)

    def broken(why: str):
        finding = _rule_error(rule, doc, why)  # REV-006: check it by hand
        return done("error", finding=finding, reason=finding.message)

    names = rule_names(rule)
    if names is None:
        return broken("expression cannot be parsed")
    sources: dict[str, tuple[AuditDocument, str]] = {}
    for name in names:
        scope, _, field = name.rpartition(".")
        target = (scopes or {}).get(scope) if scope else doc
        if target is None:
            return skipped(f"no {scope} document")
        hit = resolve(target, field, rule)
        if hit is None:
            return skipped(f"missing {name}")
        key, value = hit
        if key in config.NUMERIC_FIELDS and not _is_number(value):
            return skipped(f"{name} is not a number")
        if not (_is_number(value) or isinstance(value, str)):
            return skipped(f"{name} is not a value")
        values[name] = float(value) if _is_number(value) else value
        sources[name] = (target, key)
    try:
        ok = expression.evaluate(rule.expression, values, config.AMOUNT_TOLERANCE)
    except ExpressionError as exc:
        return broken(str(exc))
    if ok:
        return done("passed")
    evidence_ids: list[str] = []
    for target, _ in sources.values():
        if target.doc_id not in evidence_ids:
            evidence_ids.append(target.doc_id)
    shown = ", ".join(f"{n}={fmt(v)}" for n, v in values.items())
    category = config.RULE_CATEGORY.get(rule.rule_id, config.DEFAULT_RULE_CATEGORY)
    severity, note = rule.severity, ""
    difference = expression.amount_difference(rule.expression, values)
    if difference is not None:
        note = f" Difference: {fmt(difference)}."
    gap = below_materiality(rule, category, values, materiality)
    if gap is not None:
        severity = "low"
        note += (f" The difference is below the case materiality {fmt(float(materiality))};"
                 f" C2 rates this rule {rule.severity}.")
    finding = Finding(
        finding_id=f"{doc.doc_id}-{rule.rule_id}", rule_id=rule.rule_id,
        category=category, severity=severity,
        message=f"{rule.name or rule.rule_id} failed for {label(doc)}: "
                f"{rule.expression} is false ({shown}).{note}",
        evidence_ids=evidence_ids,
        confidence=min(confidence_of(t, k) for t, k in sources.values()) if sources else 1.0,
        claims=[EvidenceClaim(evidence_id=t.doc_id, field=k, claimed_value=values[n])
                for n, (t, k) in sources.items()])
    return done("failed", finding=finding, reason=finding.message)


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


_APPROVAL_COUNT = {"single": 1, "one": 1, "dual": 2, "double": 2, "two": 2,
                   "triple": 3, "three": 3}


def required_approvals(rule: RuleResponse) -> int | None:
    """How many approvals a policy needs: C2's number, else read from the rule
    text ("dual approval" = 2), else None (unknown)."""
    if rule.required_approvals is not None:
        return rule.required_approvals
    m = re.search(r"\b(single|one|dual|double|two|triple|three)\b[\s-]*(?:\w+\s+)?approv",
                  rule.text, re.IGNORECASE)
    return _APPROVAL_COUNT[m.group(1).lower()] if m else None


def policy_findings(doc: AuditDocument, rules: list[RuleResponse]) -> list[Finding]:
    return policy_check(doc, rules)[0]


def policy_check(doc: AuditDocument,
                 rules: list[RuleResponse]) -> tuple[list[Finding], list[RuleApplication]]:
    """KG policy limits, e.g. POL-07: an amount above the limit needs dual approval.
    When the document's approval stamp was read (`approvals` = signed rows), too few
    signatures is a high finding and enough is no finding. When it was not read, the
    auditor is asked to confirm the approval rather than told it is missing.
    Each rule's outcome is recorded and sent as an XAI policy_check step."""
    out: list[Finding] = []
    applied: list[RuleApplication] = []

    def record(r: RuleResponse, outcome, values=None, need=None, signed=None, finding=None,
               reason=None, detail="", trace=True) -> None:
        a = RuleApplication(
            kind="policy_check", rule_id=r.rule_id, rule_name=r.text, doc_id=doc.doc_id,
            doc_type=doc.doc_type, agent="compliance", outcome=outcome,
            expression=f"{config.POLICY_LIMIT_FIELD} <= {r.limit:g}" if r.limit is not None else "",
            values=values or {}, limit=float(r.limit) if r.limit is not None else None,
            approvals_required=need, approvals_signed=signed,
            severity=finding.severity if finding is not None else None,
            reason=reason, detail=detail, finding_id=finding.finding_id if finding is not None else None)
        applied.append(a)
        if trace:
            emit(a)

    hit = resolve(doc, config.POLICY_LIMIT_FIELD)
    if hit is None or not _is_number(hit[1]):
        for r in rules:  # no live step: the timeline only shows limits that were compared
            record(r, "skipped", reason=f"no numeric {config.POLICY_LIMIT_FIELD}", trace=False)
        return out, applied
    key, amount = hit[0], float(hit[1])
    signed = doc.fields.get(config.APPROVALS_FIELD)
    signed = float(signed) if _is_number(signed) else None
    for r in rules:
        values: dict[str, Value] = {key: amount}
        if r.limit is None:
            record(r, "skipped", values, reason="the rule has no limit", trace=False)
            continue
        limit = f"{key} {fmt(amount)} {'<=' if amount <= r.limit else '>'} limit {fmt(float(r.limit))}"
        if amount <= r.limit:
            record(r, "passed", values, detail=limit)
            continue
        need = required_approvals(r)
        above = f"{r.text} {label(doc)} has {key} {fmt(amount)} above the limit {fmt(float(r.limit))}"
        claims = [EvidenceClaim(evidence_id=doc.doc_id, field=key, claimed_value=amount)]
        if need is None or signed is None:
            outcome, severity, message = "review", "medium", f"{above}; confirm the required approval."
            confidence = confidence_of(doc, key)
            detail = f"{limit}; approvals {'not read from the document' if signed is None else 'needed: unknown'}"
        elif signed >= need:
            record(r, "passed", values, need, signed, detail=f"{limit}; {int(signed)} of {need} approvals signed")
            continue
        else:
            outcome, severity = "failed", "high"
            message = (f"{above} but only {int(signed)} of {need} required approvals "
                       f"is signed on the document.")
            confidence = confidence_of(doc, key, config.APPROVALS_FIELD)
            claims.append(EvidenceClaim(evidence_id=doc.doc_id, field=config.APPROVALS_FIELD,
                                        claimed_value=signed))
            detail = f"{limit}; {int(signed)} of {need} approvals signed"
        finding = Finding(
            finding_id=f"{doc.doc_id}-{r.rule_id}", rule_id=r.rule_id,
            category="compliance", severity=severity, message=message,
            evidence_ids=[doc.doc_id], policy_ids=[r.rule_id],
            confidence=confidence, claims=claims)
        out.append(finding)
        record(r, outcome, values, need, signed, finding, reason=message, detail=detail)
    return out, applied


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
                              f"Unrecognised document {label(d)}: doc type '{d.doc_type}' "
                              f"is not supported, needs human review.", [d.doc_id]))
        for f in missing_required(d):
            out.append(Finding(
                finding_id=f"{d.doc_id}-CHK006-{f}", rule_id="CHK-006", category="format",
                severity="medium", message=f"Missing required field '{f}' in {label(d)}.",
                evidence_ids=[d.doc_id], policy_ids=["CHK-006"]))
        if not d.fields:
            out.append(review(f"{d.doc_id}-REV004-nofields", "REV-004",
                              f"No values were read from {label(d)}, so no rule checked it. "
                              f"This is expected for a document without amounts (e.g. a goods "
                              f"received note lists only quantities and dates); it stays in the "
                              f"case as supporting evidence. If it should have amounts, check its "
                              f"fields in the Library.", [d.doc_id]))
        for fname, value in d.fields.items():
            if isinstance(value, list):
                out.append(review(f"{d.doc_id}-REV003-{fname}", "REV-003",
                                  f"Field '{fname}' in {label(d)} was read with conflicting "
                                  f"values {value!r}; needs human review.", [d.doc_id],
                                  confidence=confidence_of(d, fname)))
            elif fname in config.NUMERIC_FIELDS and value is not None and not _is_number(value):
                out.append(review(f"{d.doc_id}-REV003-{fname}", "REV-003",
                                  f"Field '{fname}' in {label(d)} holds {value!r}, which could "
                                  f"not be read as a number; needs human review.", [d.doc_id],
                                  confidence=confidence_of(d, fname)))
        for fname, conf in d.confidences.items():
            if not 0.0 <= conf <= 1.0:
                out.append(review(f"{d.doc_id}-REV004-conf-{fname}", "REV-004",
                                  f"Confidence {conf} for '{fname}' in {label(d)} is outside "
                                  f"0..1; the extraction score cannot be trusted.", [d.doc_id]))
            elif conf < config.REVIEW_CONFIDENCE_LIMIT:
                why = ("was matched to its line by AI and not confirmed by a person"
                       if d.methods.get(fname, "").endswith("c3:unconfirmed")
                       else f"has low confidence {conf:.2f}")
                out.append(review(f"{d.doc_id}-REV001-{fname}", "REV-001",
                                  f"Field '{fname}' in {label(d)} {why}; needs human review "
                                  f"(not an audit violation).", [d.doc_id], confidence=float(conf)))
        if d.parent_doc_id is not None and d.parent_doc_id not in ids:
            out.append(review(f"{d.doc_id}-REV004-parent", "REV-004",
                              f"{label(d)} says it supports {d.parent_doc_id}, which is not "
                              f"in this case.", [d.doc_id]))
        if d.source is not None and not d.source.human_verified:
            out.append(review(f"{d.doc_id}-REV008", "REV-008",
                              f"{label(d)} was read from {d.source.component.upper()}'s machine "
                              f"extraction; no person has verified it there yet.", [d.doc_id]))
    return out
