"""C3 against a fake Component-02 that answers on C2's real endpoint paths with
the mock data. If the mock and C2's contract drift apart, these fail."""
import json
import urllib.parse
from pathlib import Path

import pytest

from app.schemas.copilot import CopilotQuery
from app.services import copilot, intake, orchestrator
from app.services.kg_client import FallbackKGClient, LiveKGClient
from scripts.check_kg_contract import run_checks
from tests.conftest import doc

MOCK = json.loads((Path(__file__).resolve().parents[1] / "app" / "services" / "mock_data.json")
                  .read_text(encoding="utf-8"))


def fake_c2(overrides: dict | None = None):
    """A transport answering like C2's /query API (None = 404)."""
    def get(path: str, params: dict):
        if overrides and path in overrides:
            return overrides[path]
        parts = [urllib.parse.unquote(p) for p in path.strip("/").split("/")]
        match parts:
            case ["health"]:
                return {"status": "ok", "neo4j": "up"}
            case ["query", "fields"]:
                return MOCK["fields"]
            case ["query", "rules", rule_id, "explain"]:
                return MOCK["explanations"].get(rule_id)
            case ["query", "rules", doc_type]:
                return MOCK["rules"].get(doc_type, [])
            case ["query", "check-rules", doc_type]:
                return MOCK["check_rules"].get(doc_type, [])
            case ["query", "evidence-chain", doc_id]:
                return [doc_id]
            case ["query", "standards", code]:
                return MOCK["standards"].get(code)
            case ["query", "sections", section_id]:
                return MOCK["sections"].get(section_id)
            case ["query", "definitions", term]:
                return MOCK["definitions"].get(term)
            case ["query", "line-items", code]:
                return MOCK["line_items"].get(MOCK["fields"].get(code, code))
            case ["query", "search"]:
                return {"query": params["q"], "mode": params["mode"], "note": None,
                        "results": [{**h, "via": "keyword+semantic"} for h in MOCK["search"]]}
        return None
    return get


def live(overrides=None):
    return FallbackKGClient(mode="live", live=LiveKGClient("http://c2", transport=fake_c2(overrides)))


def test_contract_check_passes_on_c2_shaped_data():
    report = run_checks(LiveKGClient("http://c2", transport=fake_c2()), {"status": "ok", "neo4j": "up"})
    text = "\n".join(report.lines)
    assert report.problems == []
    assert "CHK-001 Accounting equation" in text and "Compliance" in text
    assert "CHK-004" in text and "Anomaly" in text
    assert "payroll: no rules" in text
    assert "POL-07 limit 100000.0" in text and "amount > limit" in text


def test_contract_check_reports_broken_replies():
    broken = {"/query/check-rules/balance_sheet": [{"rule_id": "CHK-001"}],  # no expression
              "/query/check-rules/invoice": [{"rule_id": "CHK-099", "name": "x", "expression": "a ==",
                                              "severity": "high"}]}
    report = run_checks(LiveKGClient("http://c2", transport=fake_c2(broken)), {"neo4j": "up"})
    assert any("check-rules/balance_sheet" in p for p in report.problems)
    assert any("CHK-099" in p and "cannot be evaluated" in p for p in report.problems)


def test_full_audit_through_c2_shaped_replies(store):
    kg = live()
    case = intake.normalize_case({"case_id": "LIVE-1", "docs": [
        doc("BS", "balance_sheet", {"total_assets": 100, "total_liabilities": 30, "total_equity": 20}),
        doc("INV", "invoice", {"amount": 150000, "cash_out": 150000, "purchase_basis": "credit", "asset_in": 0})]})
    result = orchestrator.run_case(case, kg, store=store)
    assert result.kg_source == "live"
    chk = next(f for f in result.findings if f.rule_id == "CHK-001")
    assert "CF:4.4" in chk.policy_ids
    assert "tests: Accuracy, Completeness" in chk.reasoning_chain
    assert "risk: Material misstatement due to error" in chk.reasoning_chain
    fraud = next(f for f in result.findings if f.rule_id == "CHK-005")
    assert "risk: Material misstatement due to fraud, Management override of controls" in fraud.reasoning_chain


def test_superseded_standard_is_flagged_not_hidden(store):
    old = dict(MOCK["explanations"]["CHK-001"])
    old["citations"] = [{"standard": "LKAS 18", "section": "LKAS 18:14"}]
    kg = live({"/query/rules/CHK-001/explain": old})
    case = intake.normalize_case({"case_id": "LIVE-2", "docs": [
        doc("BS", "balance_sheet", {"assets": 100, "liabilities": 30, "capital": 20})]})
    result = orchestrator.run_case(case, kg, store=store)
    chk = next(f for f in result.findings if f.rule_id == "CHK-001")
    assert chk.severity == "high"  # the finding itself is unchanged
    assert any("LKAS 18 is superseded, superseded by SLFRS 15" in s for s in chk.reasoning_chain)
    assert any("not current" in t.detail for t in result.trace if t.agent_name == "reasoning")


def test_kg_lookup_failures_are_reported_and_audit_continues(store):
    def flaky(path, params):
        if path.endswith("/explain"):
            return {"citations": "not a list"}  # wrong shape for every explanation
        return fake_c2()(path, params)
    kg = FallbackKGClient(mode="live", live=LiveKGClient("http://c2", transport=flaky))
    case = intake.normalize_case({"case_id": "LIVE-3", "docs": [
        doc("BS", "balance_sheet", {"assets": 100, "liabilities": 30, "capital": 20})]})
    result = orchestrator.run_case(case, kg, store=store)
    assert any(f.rule_id == "CHK-001" for f in result.findings)
    assert any("KG lookup failed" in t.detail and "explain CHK-001" in t.detail for t in result.trace)


@pytest.mark.parametrize("text,expect", [
    ("what does LKAS 2:9 say?", "lower of cost and net realisable value"),
    ("show LKAS 2 para 9", "Measurement of inventories"),
    ("define net realisable value", "Estimated selling price"),
    ("what does capital mean?", "Total equity is a line item"),
    ("what does LKAS 2 say about inventories?", "LKAS 2:9"),
])
def test_copilot_standards_answers_from_c2(store, text, expect):
    r = copilot.answer(CopilotQuery(text=text), live(), store)
    assert r.intent == "standard_search" and expect in r.reply


def test_copilot_rejects_unsafe_lookups(store):
    r = copilot.answer(CopilotQuery(text="define x') DETACH DELETE n //"), live(), store)
    assert r.intent == "standard_search" and "DETACH" not in r.reply
