import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients"))

from kg_client_http import HTTPKGClient, KGUnavailable, _urllib_transport


class Transport:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, path, params):
        self.calls.append((path, params))
        return self.answers.get(path)


def test_same_methods_as_component_03_kgclient():
    for name in ("get_rules", "get_evidence_chain", "get_postings", "get_period_totals",
                 "get_check_rules"):
        assert callable(getattr(HTTPKGClient, name))


def test_paths_are_url_encoded():
    t = Transport({"/query/sections/LKAS%202%3A9": {"section": {"id": "LKAS 2:9"}}})
    kg = HTTPKGClient(transport=t)
    assert kg.get_section("LKAS 2:9")["section"]["id"] == "LKAS 2:9"
    kg.get_period_totals("CASE TV", 2026)
    assert t.calls[-1] == ("/query/period-totals/CASE%20TV", {"year": 2026})


def test_defaults_match_c03_mock_when_nothing_found():
    kg = HTTPKGClient(transport=Transport({}))
    assert kg.get_rules("invoice") == [] and kg.get_check_rules("x") == []
    assert kg.get_evidence_chain("BS26") == ["BS26"]
    assert kg.get_period_totals("C", 2026) == {"assets": 0.0, "liabilities": 0.0,
                                               "capital": 0.0, "year": 2026}
    assert kg.explain_rule("NOPE") is None and kg.search("x y") == []


def test_search_returns_results_list():
    t = Transport({"/query/search": {"results": [{"section": "LKAS 1:25"}], "note": None}})
    assert HTTPKGClient(transport=t).search("going concern", standard="LKAS 1") == [
        {"section": "LKAS 1:25"}]
    assert t.calls[0][1]["standard"] == "LKAS 1"


def test_unreachable_server_raises_kg_unavailable(monkeypatch):
    import urllib.error
    import urllib.request

    def refuse(*_a, **_k):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    with pytest.raises(KGUnavailable, match="not reachable"):
        _urllib_transport("http://localhost:8002", timeout=1)("/query/rules/invoice", {})


def test_client_against_the_real_app(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.query import contract
    monkeypatch.setattr(contract, "get_rules", lambda doc_type: [
        {"rule_id": "POL-07", "text": "dual approval", "limit": 100000.0}])
    client = TestClient(app)
    kg = HTTPKGClient(transport=lambda path, params: client.get(path, params=params).json())
    assert kg.get_rules("invoice")[0]["rule_id"] == "POL-07"
