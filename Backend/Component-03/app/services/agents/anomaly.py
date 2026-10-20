"""Agent 3: Anomaly. KG rules that compare documents (child vs parent), years
(this year vs prior), and fraud patterns (e.g. cash out with no asset in).

A rule applies to a child/parent pair when either document's type has it.
"""
from app.schemas.case import AuditCase, AuditDocument
from app.schemas.findings import Finding, TraceEntry
from app.schemas.kg import CheckRuleResponse
from app.services import rules, xai_trace
from app.services.kg_client import KGClient, KGError


def _scopes(rule: CheckRuleResponse) -> set[str]:
    return {n.split(".", 1)[0] for n in (rules.rule_names(rule) or []) if "." in n}


def run(case: AuditCase, kg: KGClient) -> tuple[list[Finding], list[TraceEntry]]:
    findings: list[Finding] = []
    skipped: list[str] = []
    by_id = {d.doc_id: d for d in case.docs}
    loaded: dict[str, list[CheckRuleResponse]] = {}

    def rules_of(doc: AuditDocument) -> list[CheckRuleResponse] | None:
        if doc.doc_type not in loaded:
            try:
                loaded[doc.doc_type] = rules.rules_for(kg.get_check_rules(doc.doc_type), anomaly=True)
            except (ValueError, KGError) as exc:
                findings.append(rules.review(
                    f"{doc.doc_id}-REV007-anomaly", "REV-007",
                    f"Anomaly rules for {doc.doc_id} ({doc.doc_type}) could not be loaded "
                    f"from the knowledge graph: {exc}. These checks did not run.",
                    [doc.doc_id], severity="medium"))
                return None
        return loaded[doc.doc_type]

    def apply(rule, doc, scopes):
        finding, skip = rules.evaluate_rule(rule, doc, scopes, materiality=case.materiality)
        if finding:
            findings.append(finding)
        if skip:
            skipped.append(skip)

    for d in case.docs:
        own = rules_of(d)
        if own is None:
            continue
        for rule in own:
            scopes = _scopes(rule)
            if "child" in scopes or "parent" in scopes:
                continue  # handled per child/parent pair below
            if "prior" in scopes:
                prior = rules.prior_doc(case, d)
                if prior is None:
                    continue  # first year: nothing to compare with
                if isinstance(prior, str):
                    skipped.append(f"{rule.rule_id} on {d.doc_id}: {prior}")
                    xai_trace.step("rule_check", "skipped", rule_id=rule.rule_id,
                                   rule_name=rule.name, expression=rule.expression,
                                   doc_id=d.doc_id, doc_type=d.doc_type,
                                   reason=f"no single prior-year document ({prior})")
                    continue
                apply(rule, d, {"prior": prior})
            else:
                apply(rule, d, {})

        parent = by_id.get(d.parent_doc_id or "")
        if parent is None:
            continue
        pair_rules: dict[str, CheckRuleResponse] = {}
        for rule in own + (rules_of(parent) or []):
            if {"child", "parent"} & _scopes(rule):
                pair_rules.setdefault(rule.rule_id, rule)
        for rule in pair_rules.values():
            apply(rule, d, {"child": d, "parent": parent})

    trace = [TraceEntry(agent_name="anomaly", decision_type="check",
                        detail=f"Anomaly scan found {len(findings)} issue(s).")]
    trace += rules.materiality_trace("anomaly", case.materiality, findings)
    if skipped:
        trace.append(TraceEntry(agent_name="anomaly", decision_type="skip",
                                detail="Not applicable (inputs missing): " + "; ".join(skipped) + "."))
    return findings, trace
