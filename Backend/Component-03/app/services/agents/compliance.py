"""Agent 2: Compliance — equation + debit/credit + KG policy limits."""
from app.schemas.case import AuditCase
from app.schemas.findings import Finding, TraceEntry
from app.services import rule_engine
from app.services.kg_client import KGClient


def run(case: AuditCase, kg: KGClient) -> tuple[list[Finding], list[TraceEntry]]:
    findings: list[Finding] = []
    for d in case.docs:
        findings += rule_engine.check_accounting_equation(d)
        findings += rule_engine.check_debit_credit(d)
        # KG policy: e.g. dual approval limit
        for r in kg.get_rules(d.doc_type):
            limit = float(r.get("limit", 0))
            amt = d.fields.get("amount")
            if isinstance(amt, (int, float)) and amt > limit:
                findings.append(Finding(
                    finding_id=f"{d.doc_id}-{r['rule_id']}", rule_id=r["rule_id"],
                    category="compliance", severity="high",
                    message=f"{r['text']} Got {amt:.0f} in {d.doc_id}.",
                    evidence_ids=[d.doc_id], policy_ids=[r["rule_id"]]))
    trace = [TraceEntry(agent_name="compliance", decision_type="check",
                        detail=f"Compliance checked {len(case.docs)} doc(s), {len(findings)} finding(s).")]
    return findings, trace
