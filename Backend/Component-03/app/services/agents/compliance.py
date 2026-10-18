"""Agent 2: Compliance. Per-document KG check rules (accounting equation,
debit = credit, statement tie-outs) and KG policy limits.

If the KG cannot give the rules for a document type, the audit carries on and
a REV-007 review item says which checks did not run (never a clean look).
"""
from app.schemas.case import AuditCase
from app.schemas.findings import Finding, TraceEntry
from app.services import rules
from app.services.kg_client import KGClient, KGError


def run(case: AuditCase, kg: KGClient) -> tuple[list[Finding], list[TraceEntry]]:
    findings: list[Finding] = []
    skipped: list[str] = []
    ran = 0
    for d in case.docs:
        try:
            check_rules = rules.rules_for(kg.get_check_rules(d.doc_type), anomaly=False)
            policy = kg.get_rules(d.doc_type)
        except (ValueError, KGError) as exc:
            findings.append(rules.review(
                f"{d.doc_id}-REV007-compliance", "REV-007",
                f"Compliance rules for {d.doc_id} ({d.doc_type}) could not be loaded "
                f"from the knowledge graph: {exc}. These checks did not run.",
                [d.doc_id], severity="medium"))
            continue
        for rule in check_rules:
            finding, skip = rules.evaluate_rule(rule, d)
            ran += 1
            if finding:
                findings.append(finding)
            if skip:
                skipped.append(skip)
        findings += rules.policy_findings(d, policy)
    trace = [TraceEntry(agent_name="compliance", decision_type="check",
                        detail=f"Compliance ran {ran} rule check(s) on {len(case.docs)} "
                               f"document(s): {len(findings)} finding(s).")]
    if skipped:
        trace.append(TraceEntry(agent_name="compliance", decision_type="skip",
                                detail="Not applicable (inputs missing): " + "; ".join(skipped) + "."))
    return findings, trace
