from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable

from app.main import app
from app.query import contract

LINE_ITEMS = [
    {"code": "total_assets", "aliases": ["assets"]},
    {"code": "total_liabilities", "aliases": ["liabilities"]},
    {"code": "total_equity", "aliases": ["capital", "equity"]},
    {"code": "total_current_assets", "aliases": ["current_assets"]},
]


class FakeRun:
    """Answers by matching a phrase in the query, records every call."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, query, **params):
        self.calls.append((query, params))
        return next((rows for key, rows in self.answers.items() if key in query), [])


def test_check_rules_keep_c03_fields_and_add_variables():
    run = FakeRun({
        "MATCH (r:CheckRule)": [
            {"rule_id": "CHK-001", "name": "Accounting equation",
             "expression": "assets == liabilities + capital", "severity": "high"},
            {"rule_id": "CHK-007", "name": "Total assets",
             "expression": "total_assets == total_current_assets + total_non_current_assets",
             "severity": "medium"}],
        "MATCH (li:LineItem)": LINE_ITEMS,
    })
    rules = contract.get_check_rules("balance_sheet", run)
    chk1 = rules[0]
    assert {k: chk1[k] for k in ("rule_id", "name", "expression", "severity")} == {
        "rule_id": "CHK-001", "name": "Accounting equation",
        "expression": "assets == liabilities + capital", "severity": "high"}
    assert chk1["variables"][2] == {"name": "capital", "line_item": "total_equity",
                                    "aliases": ["capital", "equity"]}
    names = [v["name"] for v in rules[1]["variables"]]
    assert names == ["total_assets", "total_current_assets"]
    assert run.calls[0][1] == {"doc_type": "balance_sheet"}


def test_check_rules_for_unknown_doc_type_is_empty():
    assert contract.get_check_rules("nope", FakeRun({})) == []


def test_rules_pass_doc_type_as_parameter():
    run = FakeRun({"PolicyRule": [{"rule_id": "POL-07", "text": "t", "limit": 100000.0}]})
    assert contract.get_rules("invoice", run)[0]["limit"] == 100000.0
    assert "$doc_type" in run.calls[0][0] and run.calls[0][1] == {"doc_type": "invoice"}


def test_evidence_chain_starts_with_the_document():
    run = FakeRun({"CHILD_OF": [{"others": ["INV2", "BS26", "INV1"]}]})
    assert contract.get_evidence_chain("BS26", run) == ["BS26", "INV1", "INV2"]
    assert contract.get_evidence_chain("X", FakeRun({})) == ["X"]


def test_period_totals_shape_matches_c03_mock():
    out = contract.get_period_totals("CASE-TV", 2026, FakeRun({}))
    assert {"assets", "liabilities", "capital", "year"} <= set(out) and out["year"] == 2026


def test_field_map_includes_codes_and_aliases():
    fields = contract.field_map(FakeRun({"MATCH (li:LineItem)": LINE_ITEMS}))
    assert fields["capital"] == "total_equity" and fields["total_equity"] == "total_equity"


def test_endpoints_return_503_when_neo4j_is_down(monkeypatch):
    def down(*_a, **_k):
        raise ServiceUnavailable("down")
    monkeypatch.setattr(contract, "get_rules", down)
    assert TestClient(app).get("/query/rules/invoice").status_code == 503


def test_endpoints_route_to_contract(monkeypatch):
    monkeypatch.setattr(contract, "get_period_totals",
                        lambda case_id, year: {"case": case_id, "year": year})
    body = TestClient(app).get("/query/period-totals/CASE-TV", params={"year": 2026}).json()
    assert body == {"case": "CASE-TV", "year": 2026}
