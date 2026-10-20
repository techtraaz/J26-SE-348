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


def test_stream_endpoint():
    lines = client.post("/audit/run/stream", json=CASE).text.strip().splitlines()
    assert '"result"' in lines[-1]


def test_cases_list_shows_latest_version_per_case():
    client.post("/audit/run", json=CASE)
    client.post("/audit/run", json=CASE)
    client.post("/audit/run", json={"case_id": "API-2", "docs": [doc("I", "invoice", {"amount": 150000})]})
    cases = {c["case_id"]: c for c in client.get("/audit/cases").json()["cases"]}
    assert cases["API-1"]["version"] == 2 and cases["API-1"]["high"] == 1
    assert cases["API-2"]["findings"] == 1 and cases["API-2"]["docs"] == 1
    assert cases["API-1"]["verdict"] == "issues_found" and cases["API-1"]["score"] is not None
    assert cases["API-1"]["title"] == "Balance sheet"  # no file name: named by its type


def test_case_title_from_its_documents():
    from app.services.store import case_title
    inv = doc("I", "invoice", {}, name="04_Tax_Invoice_COI-INV-26-1158.pdf")
    po = doc("P", "purchase_order", {}, name="03a_Purchase_Order_PO-2026-0187.pdf", parent_doc_id="I")
    grn = doc("G", "goods_received_note", {}, parent_doc_id="I")
    assert case_title([inv]) == "Tax Invoice COI-INV-26-1158"
    assert case_title([po, grn, inv]) == "Tax Invoice COI-INV-26-1158 + 2 more"  # the supported document leads
    unlinked = [{**po, "parent_doc_id": None}, {**inv}]
    assert case_title(unlinked) == "Tax Invoice COI-INV-26-1158 + 1 more"  # a PO never names the case
    assert case_title([{**po, "parent_doc_id": None}]) == "Purchase Order PO-2026-0187"
    assert case_title([doc("X", "unknown", {})]) == "Unknown"
    assert case_title([]) == "Empty case"
