from fastapi.testclient import TestClient
from neo4j.time import Date, DateTime

from app.graph.neo4j_client import _plain
from app.main import app
from app.query import lookup

CITE = {"standard": "LKAS 2", "title": "Inventories", "paragraph": "9", "section": "LKAS 2:9",
        "heading": "Measurement of inventories", "text": "9  Inventories shall be measured " * 50}

CHK_011 = {
    "rule": {"rule_id": "CHK-011", "name": "Inventory not above NRV",
             "expression": "inventories <= inventory_nrv", "severity": "medium"},
    "equations": [{"code": "EQ-017", "name": "Inventory at lower of cost and NRV",
                   "expression": "inventories == min(inventory_cost, inventory_nrv)",
                   "kind": "measurement"}],
    "requirements": [{"id": "LKAS 2:9#R1", "text": "Measure at lower of cost and NRV",
                      "obligation": "shall"}],
    "assertions": ["Accuracy, valuation and allocation"],
    "risks": ["Material misstatement due to error"],
    "doc_types": ["balance_sheet"],
    "section_citations": [CITE, CITE, CITE],
    "standard_citations": [],
}


def _run(rows):
    calls = []

    def run(query, **params):
        calls.append(params)
        return [{**r} for r in rows]
    run.calls = calls
    return run


def test_explain_dedupes_citations_and_builds_sentence():
    out = lookup.explain_rule("CHK-011", _run([CHK_011]))
    assert len(out["citations"]) == 1
    assert len(out["citations"][0]["text"]) == lookup.TEXT_PREVIEW
    sentence = out["explanation"]
    assert sentence.startswith("CHK-011 Inventory not above NRV checks `inventories <= inventory_nrv`.")
    assert "Source: LKAS 2 para 9 (Inventories, Measurement of inventories)." in sentence
    assert "Applies to balance_sheet." in sentence and "Addresses: Material misstatement" in sentence


def test_explain_policy_rule_uses_text_and_limit():
    row = {"rule": {"rule_id": "POL-07", "text": "Purchases above Rs. 100,000 need dual approval.",
                    "limit": 100000.0}, "equations": [], "requirements": [], "assertions": [],
           "risks": [], "doc_types": ["invoice"], "section_citations": [],
           "standard_citations": [{"standard": "SLAuS 500", "title": "Audit Evidence"}]}
    sentence = lookup.explain_rule("POL-07", _run([row]))["explanation"]
    assert sentence.startswith("POL-07: Purchases above Rs. 100,000 need dual approval. Limit 100,000.")
    assert "Source: SLAuS 500 (Audit Evidence)." in sentence


def test_unknown_rule_is_none_and_404(monkeypatch):
    assert lookup.explain_rule("NOPE", _run([])) is None
    monkeypatch.setattr(lookup, "explain_rule", lambda rule_id: None)
    assert TestClient(app).get("/query/rules/NOPE/explain").status_code == 404


def test_equation_filters_are_parameters():
    run = _run([])
    lookup.list_equations("SCF", None, run)
    assert run.calls[0] == {"statement": "SCF", "kind": None}


def test_section_endpoint_accepts_ids_with_space_and_colon(monkeypatch):
    seen = []
    monkeypatch.setattr(lookup, "get_section", lambda sid: seen.append(sid) or {"section": {}})
    assert TestClient(app).get("/query/sections/LKAS%202:9").status_code == 200
    assert seen == ["LKAS 2:9"]


def test_neo4j_dates_become_iso_strings():
    row = {"created_at": DateTime(2026, 10, 16, 9, 30, 0), "nested": [{"d": Date(2012, 1, 1)}]}
    assert _plain(row) == {"created_at": "2026-10-16T09:30:00.000000000",
                           "nested": [{"d": "2012-01-01"}]}
