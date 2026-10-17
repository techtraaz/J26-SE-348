"""Step 4 (SO3): Reasoning attaches the KG evidence chain and turns a broken
policy -> control -> transaction -> evidence chain into a visible CHK-008 item."""
from app.schemas.case import AuditCase, AuditDocument
from app.schemas.findings import Finding
from app.services import orchestrator
from app.services.agents import reasoning
from app.services.kg_client import KGClient, KGError


def _invoice_case(case_id: str, doc_id: str) -> AuditCase:
    # amount 250,000 trips the mock POL-07 limit, so a finding cites doc_id.
    return AuditCase(case_id=case_id, docs=[
        AuditDocument(doc_id=doc_id, case_id=case_id, doc_type="invoice",
                      period_year=2026, fields={"amount": 250000})])


def test_kg_chain_appended_to_finding():
    res = orchestrator.run_case(_invoice_case("CASE-KGCHAIN", "INV-TV"), KGClient())
    pol = [f for f in res.findings if f.rule_id == "POL-07"]
    assert len(pol) == 1
    assert any("kg chain INV-TV:" in step for step in pol[0].reasoning_chain)


def test_missing_chain_evidence_becomes_chk008():
    res = orchestrator.run_case(_invoice_case("CASE-KGGAP", "INV-CASH"), KGClient())
    gaps = [f for f in res.findings if f.rule_id == "CHK-008"]
    assert len(gaps) == 1
    assert gaps[0].evidence_ids == ["INV-CASH"]
    assert gaps[0].review_status == "needs_more_evidence"
    assert "approval" in gaps[0].message


def test_complete_chain_adds_no_gap_finding():
    res = orchestrator.run_case(_invoice_case("CASE-KGOK", "INV-TV"), KGClient())
    assert [f for f in res.findings if f.rule_id == "CHK-008"] == []


def test_reasoning_without_kg_adds_no_chain_steps():
    finding = Finding(finding_id="F1", rule_id="POL-07", category="compliance",
                      severity="high", message="x", evidence_ids=["INV-CASH"])
    out, _ = reasoning.run(_invoice_case("CASE-NOKG", "INV-CASH"), [finding], None)
    assert all("kg chain" not in step for step in out[0].reasoning_chain)
    assert [f for f in out if f.rule_id == "CHK-008"] == []


class _BrokenKG(KGClient):
    def get_evidence_chain(self, doc_id: str):
        raise KGError("kg down")


def test_reasoning_survives_kg_error():
    finding = Finding(finding_id="F1", rule_id="POL-07", category="compliance",
                      severity="high", message="x", evidence_ids=["INV-CASH"])
    out, _ = reasoning.run(_invoice_case("CASE-KGERR", "INV-CASH"), [finding], _BrokenKG())
    assert out[0].review_status == "pending_review"  # finding kept, not dropped
    assert [f for f in out if f.rule_id == "CHK-008"] == []
