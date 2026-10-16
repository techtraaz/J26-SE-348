from app.schemas.case import AuditCase, AuditDocument
from app.schemas.findings import Finding
from app.services import orchestrator
from app.services.kg_client import KGClient


def _tv_case(case_id="CASE-TV"):
    return AuditCase(case_id=case_id, docs=[
        AuditDocument(doc_id="BS26", case_id=case_id, doc_type="balance_sheet",
                      period_year=2026, fields={"assets": 40000, "liabilities": 30000, "capital": 20000}),
        AuditDocument(doc_id="INV1", case_id=case_id, doc_type="invoice",
                      period_year=2026, parent_doc_id="BS26",
                      fields={"amount": 250000}),
    ])


def _clean_case(case_id="CASE-CLEAN"):
    return AuditCase(case_id=case_id, docs=[
        AuditDocument(doc_id="BS26", case_id=case_id, doc_type="balance_sheet",
                      period_year=2026, fields={"assets": 50000, "liabilities": 30000, "capital": 20000}),
        AuditDocument(doc_id="INV1", case_id=case_id, doc_type="invoice",
                      period_year=2026, parent_doc_id="BS26",
                      fields={"amount": 50000}),
    ])


def test_full_case_pending_review():
    case = _tv_case()
    res = orchestrator.run_case(case, KGClient())
    assert res.status == "pending_auditor_review"
    assert len(res.findings) >= 2  # equation + policy limit
    assert len(res.trace) == 5
    res2 = orchestrator.run_case(case, KGClient())
    assert res2.version == res.version + 1


def test_trace_five_in_execution_order_via_seq():
    res = orchestrator.run_case(_tv_case("CASE-ORD"), KGClient())
    assert len(res.trace) == 5
    by_name = {t.agent_name: t.seq for t in res.trace}
    assert set(by_name) == {"data_quality", "compliance", "anomaly", "reasoning", "evidence_validation"}
    # seq recorded at execution time, never sorted
    assert by_name["data_quality"] < by_name["compliance"]
    assert by_name["data_quality"] < by_name["anomaly"]
    assert by_name["reasoning"] > by_name["compliance"]
    assert by_name["reasoning"] > by_name["anomaly"]
    assert by_name["evidence_validation"] > by_name["reasoning"]
    # comp/anomaly may swap — both before reasoning is what matters


def test_same_input_same_findings():
    r1 = orchestrator.run_case(_tv_case("CASE-DET"), KGClient())
    r2 = orchestrator.run_case(_tv_case("CASE-DET2"), KGClient())
    assert sorted(f.rule_id for f in r1.findings) == sorted(f.rule_id for f in r2.findings)
    assert sorted(f.finding_id for f in r1.findings) == sorted(f.finding_id for f in r2.findings)


def test_ghost_id_through_full_graph():
    """Inject ghost via Compliance, assert structured fields (not trace text)."""
    from app.services.agents import compliance
    orig = compliance.run
    ghost = Finding(finding_id="X-GHOST", rule_id="CHK-003", category="arithmetic",
                    severity="high", message="planted ghost",
                    evidence_ids=["DOC-999-GHOST"], policy_ids=["CHK-003"])
    def fake_run(case, kg):
        f, t = orig(case, kg)
        return f + [ghost], t
    compliance.run = fake_run
    try:
        res = orchestrator.run_case(_tv_case("CASE-GHOST"), KGClient())
    finally:
        compliance.run = orig
    assert res.rejected_citations == ["DOC-999-GHOST"]
    assert all(f.finding_id != "X-GHOST" for f in res.findings)
    assert any(r.finding.finding_id == "X-GHOST" for r in res.rejected_findings)
    assert any(r.reason for r in res.rejected_findings)


def test_early_stop_empty_case():
    res = orchestrator.run_case(AuditCase(case_id="CASE-EMPTY", docs=[]), KGClient())
    assert len(res.trace) == 1
    assert res.trace[0].agent_name == "data_quality"
    assert res.findings == []


def test_early_stop_all_docs_rejected():
    case = AuditCase(case_id="CASE-ALLBAD", docs=[
        AuditDocument(doc_id="BS1", case_id="CASE-ALLBAD", doc_type="balance_sheet",
                      period_year=2026, fields={}),  # missing assets/liabilities/capital
    ])
    res = orchestrator.run_case(case, KGClient())
    assert set(res.rejected_records) == {"BS1"}
    assert len(res.trace) == 1  # stopped after DQ, no comp/anom/reas/val
    assert res.findings == []


def test_rejected_docs_excluded_downstream():
    case = AuditCase(case_id="CASE-MIX", docs=[
        AuditDocument(doc_id="GOOD", case_id="CASE-MIX", doc_type="invoice",
                      period_year=2026, fields={"amount": 250000}),
        AuditDocument(doc_id="BAD", case_id="CASE-MIX", doc_type="invoice",
                      period_year=2026, fields={}),  # missing amount -> DQ reject
    ])
    res = orchestrator.run_case(case, KGClient())
    assert "BAD" in res.rejected_records
    # policy check ran only on GOOD (250000 > 100000 -> 1 POL-07), BAD never reached compliance
    pol = [f for f in res.findings if f.rule_id == "POL-07"]
    assert len(pol) == 1 and pol[0].evidence_ids == ["GOOD"]


def test_clean_case_zero_findings():
    res = orchestrator.run_case(_clean_case(), KGClient())
    assert res.findings == []
    assert res.rejected_citations == []
    assert len(res.trace) == 5
