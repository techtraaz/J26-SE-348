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
    # seq stamped at execution (completion) time, never sorted; per-run 1..5
    assert sorted(by_name.values()) == [1, 2, 3, 4, 5]
    assert by_name["data_quality"] < by_name["compliance"]
    assert by_name["data_quality"] < by_name["anomaly"]
    assert by_name["reasoning"] > by_name["compliance"]
    assert by_name["reasoning"] > by_name["anomaly"]
    assert by_name["evidence_validation"] > by_name["reasoning"]


def test_same_input_same_findings():
    r1 = orchestrator.run_case(_tv_case("CASE-DET"), KGClient())
    r2 = orchestrator.run_case(_tv_case("CASE-DET2"), KGClient())
    assert sorted(f.rule_id for f in r1.findings) == sorted(f.rule_id for f in r2.findings)
    assert sorted(f.finding_id for f in r1.findings) == sorted(f.finding_id for f in r2.findings)


def test_ghost_id_through_full_graph():
    """Inject ghost via Compliance through the whole graph; assert structured fields."""
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
    assert all(r.reason for r in res.rejected_findings)


def test_claim_value_mismatch_rejected():
    """Ghost with a real doc ID but a wrong claimed value is caught by value check."""
    from app.services.agents import compliance
    from app.schemas.findings import EvidenceClaim
    orig = compliance.run
    liar = Finding(finding_id="X-LIAR", rule_id="POL-07", category="compliance",
                   severity="high", message="claims 999999 but doc holds 250000",
                   evidence_ids=["INV1"], policy_ids=["POL-07"],
                   claims=[EvidenceClaim(evidence_id="INV1", field="amount", claimed_value=999999)])
    def fake_run(case, kg):
        f, t = orig(case, kg)
        return f + [liar], t
    compliance.run = fake_run
    try:
        res = orchestrator.run_case(_tv_case("CASE-LIAR"), KGClient())
    finally:
        compliance.run = orig
    assert "INV1" in res.rejected_citations
    assert all(f.finding_id != "X-LIAR" for f in res.findings)
    assert any("claimed 999999" in r.reason for r in res.rejected_findings)


def test_reasoning_chain_filled():
    res = orchestrator.run_case(_tv_case("CASE-CHAIN"), KGClient())
    assert res.findings, "expected findings to check chains on"
    for f in res.findings:
        assert f.reasoning_chain, f"empty chain on {f.finding_id}"
        assert any(f.rule_id in step for step in f.reasoning_chain)


def test_early_stop_empty_case_not_auditable():
    res = orchestrator.run_case(AuditCase(case_id="CASE-EMPTY", docs=[]), KGClient())
    assert res.status == "not_auditable"
    assert len(res.trace) == 1
    assert res.trace[0].agent_name == "data_quality"
    assert res.findings, "DQ reasons must be included, never a bare empty result"


def test_early_stop_all_docs_rejected_not_auditable():
    case = AuditCase(case_id="CASE-ALLBAD", docs=[
        AuditDocument(doc_id="BS1", case_id="CASE-ALLBAD", doc_type="balance_sheet",
                      period_year=2026, fields={}),  # missing assets/liabilities/capital
    ])
    res = orchestrator.run_case(case, KGClient())
    assert res.status == "not_auditable"
    assert set(res.rejected_records) == {"BS1"}
    assert len(res.trace) == 1  # stopped after DQ, no comp/anom/reas/val
    assert res.findings, "DQ reasons must be included, must not look like a clean case"
    assert any("Missing required field" in f.message for f in res.findings)


def test_rejected_docs_excluded_downstream():
    case = AuditCase(case_id="CASE-MIX", docs=[
        AuditDocument(doc_id="GOOD", case_id="CASE-MIX", doc_type="invoice",
                      period_year=2026, fields={"amount": 250000}),
        AuditDocument(doc_id="BAD", case_id="CASE-MIX", doc_type="invoice",
                      period_year=2026, fields={}),  # missing amount -> DQ reject
    ])
    res = orchestrator.run_case(case, KGClient())
    assert "BAD" in res.rejected_records
    pol = [f for f in res.findings if f.rule_id == "POL-07"]
    assert len(pol) == 1 and pol[0].evidence_ids == ["GOOD"]


def test_clean_case_zero_findings():
    res = orchestrator.run_case(_clean_case(), KGClient())
    assert res.status == "pending_auditor_review"
    assert res.findings == []
    assert res.rejected_citations == []
    assert len(res.trace) == 5


def test_stream_runs_graph_once():
    from app.services.orchestrator import VERSION_STORE, stream_case
    case = _tv_case("CASE-STREAM-ONCE")
    before = VERSION_STORE.get(case.case_id, 0)
    events = list(stream_case(case, KGClient()))
    assert VERSION_STORE.get(case.case_id, 0) == before + 1
    updates = [e for e in events if e["event"] == "update"]
    results = [e for e in events if e["event"] == "result"]
    assert len(results) == 1
    assert len(results[0]["data"]["findings"]) >= 2
    assert len(updates) == 5  # one per node: dq, comp, anom, reas, val
    assert all(isinstance(e["data"], dict) for e in events)  # JSON-safe, no repr strings
