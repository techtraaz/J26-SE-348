"""KG client tests: mock data, live validation, honest fallback, safe params."""
import pytest

from app.services import kg_client
from app.services.kg_client import (
    FallbackKGClient,
    KGClient,
    KGConnectionError,
    KGDataError,
    KGProtocolError,
    LiveKGClient,
    MockKGClient,
)


def test_base_client_is_mock_by_default():
    kg = KGClient()
    assert kg.source == "mock"
    assert [r.rule_id for r in kg.get_rules("invoice")] == ["POL-07"]


def test_mock_postings_and_totals():
    kg = MockKGClient()
    postings = kg.get_postings("CASE-AMOUNT")
    assert any(p.doc_id == "TV" for p in postings)
    totals = kg.get_period_totals("CASE-AMOUNT", 2026)
    assert totals.assets == 10000.0


def test_mock_evidence_chain():
    clean = MockKGClient().get_evidence_chain("INV-TV")
    assert clean.chain == ["POL-07", "CTL-DUAL-APPROVAL", "TXN-TV", "EV-TV"]
    assert clean.missing_evidence == []
    cash = MockKGClient().get_evidence_chain("INV-CASH")
    assert cash.missing_evidence == ["approval"]


def test_demo_postings_balance_and_account_types():
    kg = MockKGClient()
    for case_id in ("CASE-TV", "CASE-CLEAN"):
        postings = kg.get_postings(case_id)
        assert postings, case_id
        assert sum(p.debit for p in postings) == sum(p.credit for p in postings)
    wrong = kg.get_postings("CASE-WRONG-SIDE")
    assert any(p.account_type == "liability" and p.account == "Office Equipment"
               for p in wrong)
    totals = kg.get_period_totals("CASE-TV", 2026)
    assert totals.assets == totals.liabilities + totals.capital


def test_unknown_ids_return_empty_not_error():
    kg = MockKGClient()
    assert kg.get_evidence_chain("NOPE").chain == []
    assert kg.get_postings("NO-CASE") == []
    assert kg.get_period_totals("NO-CASE", 2026).assets == 0.0


def test_missing_mock_file_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(kg_client, "_MOCK_PATH", tmp_path / "missing.json")
    with pytest.raises(KGDataError):
        kg_client._load_mock_file()


def test_malformed_mock_file_raises(monkeypatch, tmp_path):
    bad = tmp_path / "mock_data.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(kg_client, "_MOCK_PATH", bad)
    with pytest.raises(KGDataError):
        kg_client._load_mock_file()


def test_bad_doc_type_raises():
    with pytest.raises(ValueError):
        KGClient().get_rules("bank_statement")


def test_match_text_no_longer_blocked():
    kg = MockKGClient()
    assert kg.get_evidence_chain("match box").chain == []
    assert kg.get_evidence_chain("matchbox").chain == []
    with pytest.raises(ValueError):
        kg.get_evidence_chain("MATCH (n) RETURN n")


def _live(fetch):
    return LiveKGClient(base_url="http://kg.test", fetch=fetch)


def test_live_ok():
    def fetch(path):
        assert path == "/rules/invoice"
        return [{"rule_id": "POL-07", "text": "t", "limit": 1000}]
    kg = _live(fetch)
    rules = kg.get_rules("invoice")
    assert rules[0].limit == 1000
    assert kg.source == "live"


def test_live_malformed_is_protocol_error():
    kg = _live(lambda path: {"unexpected": True})
    with pytest.raises(KGProtocolError):
        kg.get_rules("invoice")


def test_live_connection_error():
    def boom(path):
        raise KGConnectionError("refused")
    with pytest.raises(KGConnectionError):
        _live(boom).get_rules("invoice")


def test_auto_falls_back_on_connection_error():
    def boom(path):
        raise KGConnectionError("refused")
    kg = FallbackKGClient(mode="auto", live=_live(boom), mock=MockKGClient())
    rules = kg.get_rules("invoice")
    assert rules[0].rule_id == "POL-07"
    assert kg.source == "mock_fallback"


def test_auto_does_not_fall_back_on_bad_data():
    kg = FallbackKGClient(mode="auto", live=_live(lambda path: 123),
                          mock=MockKGClient())
    with pytest.raises(KGProtocolError):
        kg.get_rules("invoice")


def test_mock_mode_never_uses_live():
    def boom(path):
        raise AssertionError("live must not be called in mock mode")
    kg = FallbackKGClient(mode="mock", live=_live(boom), mock=MockKGClient())
    assert kg.get_rules("invoice")[0].rule_id == "POL-07"
    assert kg.source == "mock"


def test_live_mode_does_not_fall_back():
    def boom(path):
        raise KGConnectionError("refused")
    kg = FallbackKGClient(mode="live", live=_live(boom), mock=MockKGClient())
    with pytest.raises(KGConnectionError):
        kg.get_rules("invoice")


def test_audit_result_reports_kg_source_and_trace():
    from app.schemas.case import AuditCase, AuditDocument
    from app.services import orchestrator

    case = AuditCase(case_id="CASE-KGSRC", docs=[
        AuditDocument(doc_id="BS", case_id="CASE-KGSRC", doc_type="balance_sheet",
                      fields={"assets": 10, "liabilities": 6, "capital": 4})])
    res = orchestrator.run_case(case, MockKGClient())
    assert res.kg_source == "mock"
    assert any(t.agent_name == "kg" for t in res.trace)


def test_full_audit_with_live_kg_down_marks_mock_fallback():
    from app.schemas.case import AuditCase, AuditDocument
    from app.services import orchestrator

    def boom(path):
        raise KGConnectionError("refused")
    kg = FallbackKGClient(mode="auto", live=_live(boom), mock=MockKGClient())
    case = AuditCase(case_id="CASE-FB", docs=[
        AuditDocument(doc_id="BS", case_id="CASE-FB", doc_type="balance_sheet",
                      period_year=2026,
                      fields={"assets": 50000, "liabilities": 30000, "capital": 20000})])
    res = orchestrator.run_case(case, kg)
    assert res.status == "pending_auditor_review"
    assert res.kg_source == "mock_fallback"
    assert any(t.agent_name == "kg" and "mock_fallback" in t.detail
               for t in res.trace)


def test_unsupported_doc_type_does_not_crash_audit():
    from app.schemas.case import AuditCase, AuditDocument
    from app.services import orchestrator

    case = AuditCase(case_id="CASE-BADTYPE", docs=[
        AuditDocument(doc_id="X1", case_id="CASE-BADTYPE",
                      doc_type="bank_statement", period_year=2026,
                      fields={"amount": 10})])
    res = orchestrator.run_case(case, MockKGClient())
    # The only doc is unrecognised: not_auditable, one REV-002, never a duplicate.
    assert res.status == "not_auditable"
    assert any(f.rule_id == "REV-002" and "not supported" in f.message
               for f in res.findings)
    assert not any(f.rule_id == "CHK-007" for f in res.findings)


def test_kg_rules_endpoint_rejects_bad_doc_type_with_4xx():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    bad = client.get("/kg/rules/bank_statement")
    assert 400 <= bad.status_code < 500
    ok = client.get("/kg/rules/invoice")
    assert ok.status_code == 200
    assert ok.json()["rules"][0]["rule_id"] == "POL-07"
