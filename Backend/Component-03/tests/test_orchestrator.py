import pytest

from app.schemas.case import AuditCase, AuditDocument
from app.schemas.findings import EvidenceClaim, Finding
from app.services import orchestrator
from app.services.kg_client import KGClient


def _agent_trace(res):
    """The five pipeline trace entries, excluding the kg-source notice line."""
    return [t for t in res.trace if t.agent_name != "kg"]


class FakeKG(KGClient):
    """Same doors, different limit — proves injection through config really works."""
    def get_rules(self, doc_type: str) -> list[dict]:
        if doc_type == "invoice":
            return [{"rule_id": "POL-07",
                     "text": "Purchases above Rs. 1,000 need dual approval (fake KG).",
                     "limit": 1000}]
        return []


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
    assert len(_agent_trace(res)) == 5
    res2 = orchestrator.run_case(case, KGClient())
    assert res2.version == res.version + 1


def test_trace_five_in_execution_order_via_seq():
    res = orchestrator.run_case(_tv_case("CASE-ORD"), KGClient())
    agent_trace = _agent_trace(res)
    assert len(agent_trace) == 5
    by_name = {t.agent_name: t.seq for t in agent_trace}
    assert set(by_name) == {"data_quality", "compliance", "anomaly", "reasoning", "evidence_validation"}
    # per-run seq 1..5, stamped at execution (completion) time, never sorted
    assert sorted(by_name.values()) == [1, 2, 3, 4, 5]
    assert by_name["data_quality"] < by_name["compliance"]
    assert by_name["data_quality"] < by_name["anomaly"]
    assert by_name["reasoning"] > by_name["compliance"]
    assert by_name["reasoning"] > by_name["anomaly"]
    assert by_name["evidence_validation"] > by_name["reasoning"]


def test_seq_resets_per_run():
    r1 = orchestrator.run_case(_tv_case("CASE-SEQ1"), KGClient())
    r2 = orchestrator.run_case(_tv_case("CASE-SEQ2"), KGClient())
    assert sorted(t.seq for t in _agent_trace(r1)) == [1, 2, 3, 4, 5]
    assert sorted(t.seq for t in _agent_trace(r2)) == [1, 2, 3, 4, 5]


def test_same_input_same_findings():
    r1 = orchestrator.run_case(_tv_case("CASE-DET"), KGClient())
    r2 = orchestrator.run_case(_tv_case("CASE-DET2"), KGClient())
    assert sorted(f.rule_id for f in r1.findings) == sorted(f.rule_id for f in r2.findings)
    assert sorted(f.finding_id for f in r1.findings) == sorted(f.finding_id for f in r2.findings)


def test_fake_kg_changes_limit():
    """Fake KG with limit 1,000: a 50,000 invoice must now trip POL-07."""
    case = _clean_case("CASE-FAKEKG")
    real = orchestrator.run_case(case, KGClient())
    assert [f for f in real.findings if f.rule_id == "POL-07"] == []
    fake = orchestrator.run_case(case, FakeKG())
    pol = [f for f in fake.findings if f.rule_id == "POL-07"]
    assert len(pol) == 1 and "1,000" in pol[0].message


def _run_case_with_docs(case_id, docs):
    return orchestrator.run_case(AuditCase(case_id=case_id, docs=docs), KGClient())


def test_chk002_wrong_side_survives_validation():
    res = _run_case_with_docs("CASE-CHK002", [
        AuditDocument(doc_id="LED1", case_id="CASE-CHK002", doc_type="ledger",
                      period_year=2026, fields={"debit_total": 100.0, "credit_total": 90.0}),
    ])
    got = [f for f in res.findings if f.rule_id == "CHK-002"]
    assert len(got) == 1 and not got[0].citation_unverified


def test_chk003_mismatch_survives_validation():
    res = _run_case_with_docs("CASE-CHK003", [
        AuditDocument(doc_id="CASH", case_id="CASE-CHK003", doc_type="ledger",
                      period_year=2026, fields={"amount": 10000.0}),
        AuditDocument(doc_id="TV", case_id="CASE-CHK003", doc_type="invoice",
                      period_year=2026, parent_doc_id="CASH", fields={"amount": 5000.0}),
    ])
    got = [f for f in res.findings if f.rule_id == "CHK-003"]
    assert len(got) == 1 and not got[0].citation_unverified


def test_chk005_cash_fraud_survives_validation():
    res = _run_case_with_docs("CASE-CHK005", [
        AuditDocument(doc_id="INV9", case_id="CASE-CHK005", doc_type="invoice",
                      period_year=2026,
                      fields={"amount": 10000.0, "cash_out": 10000.0,
                              "purchase_basis": "credit", "asset_in": 0.0}),
    ])
    got = [f for f in res.findings if f.rule_id == "CHK-005"]
    assert len(got) == 1 and not got[0].citation_unverified


def test_chk004_year_jump_survives_validation():
    res = _run_case_with_docs("CASE-CHK004", [
        AuditDocument(doc_id="BS24", case_id="CASE-CHK004", doc_type="balance_sheet",
                      period_year=2024, fields={"assets": 50000.0, "liabilities": 30000.0, "capital": 20000.0}),
        AuditDocument(doc_id="BS26", case_id="CASE-CHK004", doc_type="balance_sheet",
                      period_year=2026, fields={"assets": 90000.0, "liabilities": 30000.0, "capital": 60000.0}),
    ])
    got = [f for f in res.findings if f.rule_id == "CHK-004"]
    assert len(got) == 1 and not got[0].citation_unverified


def test_ghost_id_through_full_graph(monkeypatch):
    """Inject ghost via Compliance; kept flagged AND logged with reason."""
    from app.services.agents import compliance
    orig = compliance.run
    ghost = Finding(finding_id="X-GHOST", rule_id="CHK-003", category="arithmetic",
                    severity="high", message="planted ghost",
                    evidence_ids=["DOC-999-GHOST"], policy_ids=["CHK-003"])
    def fake_run(case, kg):
        f, t = orig(case, kg)
        return f + [ghost], t
    monkeypatch.setattr(compliance, "run", fake_run)
    res = orchestrator.run_case(_tv_case("CASE-GHOST"), KGClient())
    assert res.rejected_citations == ["DOC-999-GHOST"]
    kept = [f for f in res.findings if f.finding_id == "X-GHOST"]
    assert len(kept) == 1 and kept[0].citation_unverified is True
    assert any(r.finding.finding_id == "X-GHOST" for r in res.rejected_findings)
    assert all(r.reason for r in res.rejected_findings)


def test_claim_value_mismatch_flagged_not_dropped(monkeypatch):
    """Real doc ID but wrong claimed value: kept flagged + logged with actual value."""
    from app.services.agents import compliance
    orig = compliance.run
    liar = Finding(finding_id="X-LIAR", rule_id="POL-07", category="compliance",
                   severity="high", message="claims 999999 but doc holds 250000",
                   evidence_ids=["INV1"], policy_ids=["POL-07"],
                   claims=[EvidenceClaim(evidence_id="INV1", field="amount", claimed_value=999999)])
    def fake_run(case, kg):
        f, t = orig(case, kg)
        return f + [liar], t
    monkeypatch.setattr(compliance, "run", fake_run)
    res = orchestrator.run_case(_tv_case("CASE-LIAR"), KGClient())
    assert "INV1" in res.rejected_citations
    kept = [f for f in res.findings if f.finding_id == "X-LIAR"]
    assert len(kept) == 1 and kept[0].citation_unverified is True
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
    assert len(_agent_trace(res)) == 1
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
    assert len(_agent_trace(res)) == 1  # stopped after DQ, no comp/anom/reas/val
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
    assert len(_agent_trace(res)) == 5


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


def test_stream_not_auditable_carries_reasons():
    from app.services.orchestrator import stream_case
    events = list(stream_case(AuditCase(case_id="CASE-EMPTY-STR", docs=[]),
                              KGClient()))
    results = [e for e in events if e["event"] == "result"]
    assert len(results) == 1
    data = results[0]["data"]
    assert data["status"] == "not_auditable"
    assert data["findings"]  # DQ reasons present, never a clean-looking result
    assert any(t["agent_name"] == "kg" for t in data["trace"])


def test_latency_ms_is_measured():
    res = orchestrator.run_case(_tv_case("CASE-LAT"), KGClient())
    assert isinstance(res.latency_ms, float)
    assert res.latency_ms >= 0.0


def test_seq_from_missing_config_raises_clear_error():
    from app.services.orchestrator import OrchestratorConfigError, _seq_from
    for bad in (None, {}, {"configurable": {}}):
        with pytest.raises(OrchestratorConfigError):
            _seq_from(bad)


def test_low_confidence_finding_marked_needs_more_evidence():
    case = AuditCase(case_id="CASE-REVIEW", docs=[
        AuditDocument(doc_id="BS1", case_id="CASE-REVIEW",
                      doc_type="balance_sheet", period_year=2026,
                      fields={"assets": 50000, "liabilities": 30000, "capital": 20000},
                      confidences={"assets": 0.4})])
    res = orchestrator.run_case(case, KGClient())
    low = [f for f in res.findings if f.confidence < 0.5]
    assert low and all(f.review_status == "needs_more_evidence" for f in low)
    others = [f for f in res.findings if f.confidence >= 0.5]
    assert all(f.review_status == "pending_review" for f in others)
    assert any(t.agent_name == "reasoning" and t.decision_type == "review"
               for t in res.trace)


def test_normal_findings_stay_pending_review():
    res = orchestrator.run_case(_tv_case("CASE-NORMAL-REVIEW"), KGClient())
    assert res.findings
    assert all(f.review_status == "pending_review" for f in res.findings)
