import pytest
from fastapi.testclient import TestClient

from app.api import kg
from app.construction import service
from app.construction.context import SeedReader
from app.construction.documents import LoadedDocument, Page
from app.construction.llm import FakeLLM
from app.construction.pipeline import KGPipeline
from app.main import app

PAGE = """Measurement of inventories

9  Inventories shall be measured at the lower of cost and net realisable
value.

41  An entity shall disclose the carrying amount of inventories pledged as security."""

ANSWER = {"Paragraph: 41\n": {"is_normative": True, "requirements": [
    {"text": "Disclose inventories pledged as security", "type": "disclosure",
     "obligation": "shall"}]}}


@pytest.fixture
def client(monkeypatch):
    written = []
    llm = FakeLLM(ANSWER)

    def fake_build(write=True, max_chunks=None):
        run = (lambda q, **p: written.append(q) or []) if write else None
        return KGPipeline(llm, SeedReader(), run_write=run, max_chunks=max_chunks, embed=False)

    monkeypatch.setattr(service, "build_pipeline", fake_build)
    monkeypatch.setattr(kg, "load_pdf", lambda path, code=None: LoadedDocument(
        file=path.name, code=code or "LKAS 2", source="pdf", pages=[Page(1, PAGE)]))
    kg.JOBS.clear()
    c = TestClient(app)
    c.written = written
    return c


def test_pdf_upload_runs_as_a_job(client):
    resp = client.post("/kg/ingest/pdf", files={"file": ("LKAS_02_Inventories.pdf", b"%PDF-1.4",
                                                         "application/pdf")})
    assert resp.status_code == 202
    job = client.get(f"/kg/jobs/{resp.json()['job_id']}").json()
    assert job["status"] == "done" and job["code"] == "LKAS 2"
    assert job["summary"]["requirements"] == 1 and job["summary"]["created"]["Requirement"] == 1
    assert client.written


def test_code_param_is_passed_to_the_loader(client):
    resp = client.post("/kg/ingest/pdf", params={"code": "LKAS 42", "write": False},
                       files={"file": ("scan.pdf", b"%PDF", "application/pdf")})
    job = client.get(f"/kg/jobs/{resp.json()['job_id']}").json()
    assert job["code"] == "LKAS 42" and job["summary"]["created"]["Standard"] == 1


def test_dry_run_does_not_write(client):
    resp = client.post("/kg/ingest/pdf", params={"write": False},
                       files={"file": ("LKAS_02_Inventories.pdf", b"%PDF", "application/pdf")})
    assert client.get(f"/kg/jobs/{resp.json()['job_id']}").json()["summary"]["written"] == 0
    assert client.written == []


def test_rejects_non_pdf(client):
    resp = client.post("/kg/ingest/pdf", files={"file": ("notes.txt", b"hi", "text/plain")})
    assert resp.status_code == 400


def test_ocr_result_from_component_01(client):
    body = {"file": "LKAS_02_scan.pdf", "result": {
        "engine": {"name": "paddle", "version": "3", "settings": {}},
        "pages": [{"page_number": 1, "width": 600, "height": 800, "elapsed_ms": 4.0, "lines": [
            {"text": "41  An entity shall disclose the carrying amount of inventories",
             "confidence": 0.9, "box": [10, 100, 500, 120],
             "polygon": [[10, 100], [500, 100], [500, 120], [10, 120]]},
            {"text": "pledged as security.", "confidence": 0.5, "box": [10, 122, 200, 142],
             "polygon": [[10, 122], [200, 122], [200, 142], [10, 142]]},
        ]}]}}
    job_id = client.post("/kg/ingest/ocr", json=body).json()["job_id"]
    job = client.get(f"/kg/jobs/{job_id}").json()
    assert job["source"] == "ocr" and job["status"] == "done"
    assert job["summary"]["requirements"] == 1


def test_failed_job_reports_error(client, monkeypatch):
    def broken(**_):
        raise RuntimeError("neo4j down")
    monkeypatch.setattr(service, "build_pipeline", broken)
    resp = client.post("/kg/ingest/pdf", files={"file": ("a.pdf", b"%PDF", "application/pdf")})
    job = client.get(f"/kg/jobs/{resp.json()['job_id']}").json()
    assert job["status"] == "failed" and "neo4j down" in job["error"]


def test_unknown_job_and_listing(client):
    assert client.get("/kg/jobs/nope").status_code == 404
    client.post("/kg/ingest/pdf", files={"file": ("a.pdf", b"%PDF", "application/pdf")})
    assert len(client.get("/kg/jobs").json()) == 1


def test_pipeline_diagram(client):
    text = client.get("/kg/pipeline").text
    assert "retrieve_context" in text and "resolve" in text
