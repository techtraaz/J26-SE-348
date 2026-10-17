"""Agent 2: Compliance — equation + debit/credit + KG policy limits.

If the KG does not support a document's type, the audit does not crash: the
policy check for that document is skipped, a visible "needs review" finding is
added, and a trace line records the skip. The rest of the case still runs.
"""
from app.schemas.case import AuditCase
from app.schemas.findings import EvidenceClaim, Finding, TraceEntry
from app.services import rule_engine
from app.services.kg_client import KGClient


def _field(rule, key: str, default=None):
    """Read a rule field whether the KG client returns a model or a plain dict."""
    if isinstance(rule, dict):
        return rule.get(key, default)
    return getattr(rule, key, default)


def run(case: AuditCase, kg: KGClient) -> tuple[list[Finding], list[TraceEntry]]:
    findings: list[Finding] = []
    unsupported: list[str] = []
    for d in case.docs:
        findings += rule_engine.check_accounting_equation(d)
        findings += rule_engine.check_debit_credit(d)
        try:
            rules = kg.get_rules(d.doc_type)
        except ValueError:
            unsupported.append(d.doc_id)
            findings.append(Finding(
                finding_id=f"{d.doc_id}-CHK007-doctype", rule_id="CHK-007",
                category="format", severity="low",
                message=(f"Document type '{d.doc_type}' in {d.doc_id} is not "
                         f"supported by the knowledge graph; policy checks "
                         f"skipped, needs review."),
                evidence_ids=[d.doc_id]))
            continue
        # KG policy: e.g. dual approval limit
        for r in rules:
            rule_id = _field(r, "rule_id")
            limit = float(_field(r, "limit", 0) or 0)
            text = _field(r, "text", "")
            amt = d.fields.get("amount")
            if isinstance(amt, (int, float)) and amt > limit:
                findings.append(Finding(
                    finding_id=f"{d.doc_id}-{rule_id}", rule_id=rule_id,
                    category="compliance", severity="high",
                    message=f"{text} Got {amt:.0f} in {d.doc_id}.",
                    evidence_ids=[d.doc_id], policy_ids=[rule_id],
                    claims=[EvidenceClaim(evidence_id=d.doc_id, field="amount",
                                           claimed_value=float(amt))]))
    trace = [TraceEntry(agent_name="compliance", decision_type="check",
                        detail=f"Compliance checked {len(case.docs)} doc(s), {len(findings)} finding(s).")]
    if unsupported:
        trace.append(TraceEntry(
            agent_name="compliance", decision_type="skip",
            detail=(f"Skipped KG policy checks: unsupported doc type for "
                    f"{', '.join(unsupported)}.")))
    return findings, trace
