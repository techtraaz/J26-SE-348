from fastapi.testclient import TestClient

from app.main import app
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
