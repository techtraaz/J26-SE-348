import io
import urllib.error

import pytest

from app.services import kg_client
from app.services.kg_client import (
    FallbackKGClient,
    KGProtocolError,
    KGUnavailable,
    LiveKGClient,
    MockKGClient,
)

# Replies exactly as Component-02 sends them (docs/query_api.md).
C2 = {
    "/query/rules/invoice": [{"rule_id": "POL-07", "text": "Dual approval.", "limit": 100000.0}],
    "/query/check-rules/balance_sheet": [{
        "rule_id": "CHK-001", "name": "Accounting equation",
        "expression": "assets == liabilities + capital", "severity": "high",
        "variables": [{"name": "capital", "line_item": "total_equity", "aliases": ["capital", "equity"]}]}],
    "/query/evidence-chain/INV-1": ["INV-1", "RC-1"],
    "/query/rules/CHK-001/explain": {"rule": {}, "citations": [{"standard": "CF", "section": "CF:4.4"}],
                                     "explanation": "CHK-001 ..."},
}


def transport(calls):
    def get(path, params):
        calls.append((path, params))
        return C2.get(path)  # None == C2's 404
    return get


def test_live_client_reads_c2_shapes():
    calls = []
    kg = LiveKGClient("http://c2", transport=transport(calls))
    assert kg.get_rules("invoice")[0].limit == 100000.0
    rule = kg.get_check_rules("balance_sheet")[0]
    assert rule.variables[0].line_item == "total_equity"
    assert kg.get_evidence_chain("INV-1") == ["INV-1", "RC-1"]
    assert kg.get_evidence_chain("NOPE") == ["NOPE"]  # 404 -> just the doc
    assert kg.explain_rule("CHK-001").citations[0].ref == "CF:4.4"
    assert kg.explain_rule("CHK-999") is None
    kg.get_check_rules("balance_sheet")
    assert [c[0] for c in calls].count("/query/check-rules/balance_sheet") == 1  # cached


def test_bad_reply_shape_is_a_protocol_error():
    kg = LiveKGClient("http://c2", transport=lambda p, q: {"not": "a list"})
    with pytest.raises(KGProtocolError):
        kg.get_check_rules("balance_sheet")


def test_parameters_are_validated_before_any_call():
    kg = LiveKGClient("http://c2", transport=lambda p, q: pytest.fail("called"))
    with pytest.raises(ValueError):
        kg.get_rules("x) DETACH DELETE n //")
    with pytest.raises(ValueError):
        kg.get_evidence_chain("a'}]->(n)")


def _http_error(code):
    def opener(url, timeout):
        raise urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(b""))
    return opener


def test_http_status_mapping(monkeypatch):
    kg = LiveKGClient("http://c2")
    monkeypatch.setattr(kg_client.urllib.request, "urlopen", _http_error(404))
    assert kg.get_check_rules("invoice") == []
    monkeypatch.setattr(kg_client.urllib.request, "urlopen", _http_error(503))
    with pytest.raises(KGUnavailable):
        kg.get_rules("receipt")
    monkeypatch.setattr(kg_client.urllib.request, "urlopen", _http_error(500))
    with pytest.raises(KGProtocolError):  # a reply, not an outage: never masked by mock
        kg.get_rules("payroll")


def test_auto_mode_falls_back_once_and_says_so():
    calls = []

    def down(path, params):
        calls.append(path)
        raise KGUnavailable("refused")
    kg = FallbackKGClient(mode="auto", live=LiveKGClient("http://c2", transport=down))
    assert kg.source == "live"
    assert kg.get_rules("invoice")[0].rule_id == "POL-07"  # from mock
    kg.get_check_rules("balance_sheet")
    assert kg.source == "mock_fallback" and "refused" in kg.fallback_reason
    assert len(calls) == 1  # no repeated timeouts after the first failure


def test_auto_mode_never_masks_bad_data():
    kg = FallbackKGClient(mode="auto", live=LiveKGClient("http://c2", transport=lambda p, q: 5))
    with pytest.raises(KGProtocolError):
        kg.get_rules("invoice")


def test_mock_has_c2_rules():
    kg = MockKGClient()
    ids = {r.rule_id for r in kg.get_check_rules("balance_sheet")}
    assert {"CHK-001", "CHK-004", "CHK-007", "CHK-011"} <= ids
    assert kg.search("inventories net realisable")[0]["section"] == "LKAS 2:9"
