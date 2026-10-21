import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.api import kg, policies
from app.construction import service
from app.construction.context import SeedReader
from app.construction.documents import LoadedDocument, Page
from app.construction.llm import FakeLLM, LLMUnavailable
from app.construction.pipeline import KGPipeline
from app.main import app
from app.storage.objects import NotFound, ObjectStore, StorageNotConfigured, StoredObject

PAGE = """Measurement of inventories

9  Inventories shall be measured at the lower of cost and net realisable
value.

41  An entity shall disclose the carrying amount of inventories pledged as security."""

ANSWER = {"Paragraph: 41\n": {"is_normative": True, "requirements": [
    {"text": "Disclose inventories pledged as security", "type": "disclosure",
     "obligation": "shall"}]}}


class MemoryStore(ObjectStore):
    def __init__(self):
        super().__init__(None, "uploads")
        self.objects: dict[str, tuple[bytes, str, dict]] = {}

    def put(self, key, data, content_type, metadata=None):
        self.objects[key] = (data, content_type, metadata or {})

    def get(self, key):
        if key not in self.objects:
            raise NotFound(key)
        data, content_type, _ = self.objects[key]
        return data, content_type

    def head(self, key):
        data, _, meta = self.objects[key]
        return {"size": len(data), "metadata": meta, "last_modified": "2026-10-21T00:00:00"}

    def list(self, prefix):
        now = datetime.now(UTC).isoformat()
        return [StoredObject(k, len(v[0]), now) for k, v in self.objects.items()
                if k.startswith(prefix)]


@pytest.fixture
def store(monkeypatch):
    s = MemoryStore()
    monkeypatch.setattr(policies, "get_store", lambda: s)
    return s


@pytest.fixture
def client(monkeypatch, store):
    llm = FakeLLM(ANSWER)
    totals = iter([{"nodes": 100, "relationships": 200}, {"nodes": 108, "relationships": 215}])

    def fake_build(write=True, max_chunks=None):
        return KGPipeline(llm, SeedReader(), run_write=lambda q, **p: [], max_chunks=max_chunks,
                          embed=False)

    monkeypatch.setattr(service, "build_pipeline", fake_build)
    monkeypatch.setattr(service, "graph_totals", lambda: next(totals))
    monkeypatch.setattr(policies, "load_pdf", lambda path, code=None: LoadedDocument(
        file=path.name, code=code or "LKAS 2", source="pdf", pages=[Page(1, PAGE)]))
    kg.JOBS.clear()
    return TestClient(app)


def _upload(client, name="LKAS_02_Inventories.pdf", **data):
    return client.post("/policies", files={"file": (name, b"%PDF-1.4", "application/pdf")},
                       data=data)


def test_upload_stores_the_pdf_and_updates_the_graph(client, store):
    resp = _upload(client)
    assert resp.status_code == 202
    assert store.objects["c02-policies/LKAS_02_Inventories.pdf"][0] == b"%PDF-1.4"

    job = client.get(f"/kg/jobs/{resp.json()['job']['job_id']}").json()
    assert job["status"] == "done" and job["policy"] == "LKAS_02_Inventories.pdf"
    assert job["stage"] is None and job["stages_done"][-1] == "write"
    assert job["totals"]["after"]["nodes"] == 108
    assert [r["caption"] for r in job["changes"]["new"]["Requirement"]] == \
        ["Disclose inventories pledged as security"]
    links = job["changes"]["graph"]["links"]
    assert {"source": "Section:LKAS 2:41", "target": "Requirement:LKAS 2:41#R1",
            "type": "HAS_REQUIREMENT"} in links

    saved = json.loads(store.objects["c02-policies/_runs/LKAS_02_Inventories.pdf.json"][0])
    assert saved["status"] == "done" and saved["changes"]["new"]["Requirement"]


def test_list_shows_last_run_even_after_restart(client):
    _upload(client)
    kg.JOBS.clear()
    body = client.get("/policies").json()
    assert [p["name"] for p in body["policies"]] == ["LKAS_02_Inventories.pdf"]
    run = body["policies"][0]["last_run"]
    assert run["status"] == "done" and run["requirements"] == 1
    assert run["added"] == {"nodes": 8, "relationships": 15}
    assert client.get("/policies/LKAS_02_Inventories.pdf/run").json()["status"] == "done"


def test_code_is_kept_for_a_rerun(client, store):
    _upload(client, name="scan.pdf", code="LKAS 42")
    assert store.objects["c02-policies/scan.pdf"][2]["code"] == "LKAS 42"
    job = client.post("/policies/scan.pdf/ingest").json()
    assert job["code"] == "LKAS 42"


def test_rejects_non_pdf_and_unknown_names(client):
    assert _upload(client, name="notes.txt").status_code == 400
    assert client.post("/policies/missing.pdf/ingest").status_code == 404
    assert client.get("/policies/missing.pdf/run").status_code == 404


def test_file_is_served_inline(client):
    _upload(client)
    resp = client.get("/policies/LKAS_02_Inventories.pdf/file")
    assert resp.content == b"%PDF-1.4" and resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-disposition"].startswith("inline")


def test_busy_policy_is_not_started_twice(client):
    kg.JOBS["x"] = {"job_id": "x", "policy": "a.pdf", "status": "running",
                    "queued_at": "2026-10-21T00:00:00"}
    assert _upload(client, name="a.pdf").status_code == 409


def test_llm_offline_still_writes_paragraphs(client, monkeypatch):
    class Down(FakeLLM):
        def extract(self, system, user, schema):
            self.calls.append(user)
            raise LLMUnavailable("LLM server unavailable")

    down = Down()
    monkeypatch.setattr(service, "build_pipeline", lambda write=True, max_chunks=None: KGPipeline(
        down, SeedReader(), run_write=lambda q, **p: [], embed=False))
    job = client.get(f"/kg/jobs/{_upload(client).json()['job']['job_id']}").json()
    assert job["status"] == "done" and len(down.calls) == 1
    assert job["summary"]["llm_unavailable"] and job["summary"]["llm_errors"] == 2
    assert "Section" in job["changes"]["new"] and "Requirement" not in job["changes"]["new"]


def test_storage_not_configured(client, monkeypatch):
    def missing():
        raise StorageNotConfigured("set GARAGE_ENDPOINT")
    monkeypatch.setattr(policies, "get_store", missing)
    assert client.get("/policies").status_code == 503
