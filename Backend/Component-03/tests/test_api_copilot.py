import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.copilot import CopilotQuery
from app.services import copilot, llm
from app.services.store import StoreError
from tests.conftest import doc

client = TestClient(app)
CASE = {"case_id": "API-1", "docs": [
    doc("BS", "balance_sheet", {"assets": 100, "liabilities": 30, "capital": 20})]}


def test_run_then_read_versions():
    assert client.post("/audit/run", json=CASE).json()["version"] == 1
    assert client.post("/audit/run", json=CASE).json()["version"] == 2
    assert [v["version"] for v in client.get("/audit/API-1/versions").json()["versions"]] == [1, 2]
    assert client.get("/audit/API-1/versions/1").json()["case"]["docs"][0]["doc_id"] == "BS"
    assert client.get("/audit/API-1/latest").json()["version"] == 2
    assert client.get("/audit/API-1/versions/9").status_code == 404


def test_append_endpoint():
    client.post("/audit/run", json=CASE)
    r = client.post("/audit/API-1/evidence",
                    json={"docs": [doc("INV", "invoice", {"amount": 150000})]})
    assert r.status_code == 200 and r.json()["version"] == 2
    assert client.post("/audit/NONE/evidence", json={"docs": []}).status_code == 404


def test_bad_intake_is_422_and_store_outage_is_503(monkeypatch):
    assert client.post("/audit/run", json={"case_id": "x!", "docs": []}).status_code == 422

    def boom(*a, **k):
        raise StoreError("down")
    monkeypatch.setattr("app.services.orchestrator.run_case", boom)
    assert client.post("/audit/run", json=CASE).status_code == 503


def test_c1_intake_endpoint_can_run():
    body = {"case_id": "C1-CASE", "documents": [{"doc_type": "invoice", "period_year": 2026,
            "extraction": {"document_id": "INV-1", "run": {"status": "succeeded"}, "regions": [
                {"sequence": 1, "page_number": 1, "text": "Rs. 125,000", "confidence": 0.9,
                 "provenance": "paddleocr", "field_key": "amount"}]}}]}
    out = client.post("/audit/intake/c1?run=true", json=body).json()
    assert out["case"]["docs"][0]["fields"]["amount"] == 125000.0
    assert any(f["rule_id"] == "POL-07" for f in out["result"]["findings"])


def test_stream_endpoint():
    lines = client.post("/audit/run/stream", json=CASE).text.strip().splitlines()
    assert '"result"' in lines[-1]


@pytest.mark.parametrize("text,has_docs,intent", [
    ("What is the dual approval limit for invoices?", False, "rule_query"),
    ("explain CHK-004", False, "rule_query"),
    ("what does LKAS 2 say about inventories", False, "rule_query"),
    ("add this new receipt to the case", True, "evidence_append"),
    ("attach the bank statement", True, "evidence_append"),
    ("run a fresh audit on these", True, "fresh_audit"),
    ("please check these documents", True, "fresh_audit"),
    ("what is materiality", False, "rule_query"),
    ("my address changed", True, "fresh_audit"),  # 'add' only as a whole word
])
def test_classify(text, has_docs, intent):
    assert copilot.classify(text, has_docs) == intent


def test_copilot_rule_query_reads_kg():
    r = client.post("/copilot/query", json={"text": "rules for invoice and explain CHK-001"}).json()
    assert r["intent"] == "rule_query" and "POL-07" in r["reply"] and "CHK-001" in r["reply"]


def test_copilot_fresh_then_append(kg, store):
    fresh = copilot.answer(CopilotQuery(text="fresh audit", case_id="CP", docs=CASE["docs"]), kg, store)
    assert fresh.intent == "fresh_audit" and fresh.data["version"] == 1
    added = copilot.answer(CopilotQuery(text="add this invoice", case_id="CP",
                                        docs=[doc("INV", "invoice", {"amount": 5})]), kg, store)
    assert added.intent == "evidence_append" and added.data["version"] == 2
    missing = copilot.answer(CopilotQuery(text="add this", case_id="CP"), kg, store)
    assert missing.data is None and "docs" in missing.reply


def test_llm_line_must_only_repeat_given_numbers():
    assert llm.is_safe("3 findings for 2 docs", "case has 3 findings for 2 docs")
    assert not llm.is_safe("3 findings, Rs. 9,000 lost", "case has 3 findings")
    assert not llm.is_safe("breaks GDPR", "x")
