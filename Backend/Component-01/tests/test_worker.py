"""Worker and background-job tests: failures, retry, recovery, concurrency."""

import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Document, ExtractionRun, Page, Region
from app.jobs.worker import JobWorker
from app.main import create_app
from app.schemas.extraction import EngineInfo
from app.services.ocr.base import OCREngine, PageRecognition
from tests.conftest import make_png, make_tiff


@pytest.fixture
def client(make_settings):
    with TestClient(create_app(make_settings())) as c:
        yield c


def _upload(client, data: bytes, name="invoice.png"):
    return client.post("/api/v1/documents", files={"file": (name, data)})


class BoomEngine(OCREngine):
    """An engine that always fails, with an internal detail that must not leak."""

    def info(self) -> EngineInfo:
        return EngineInfo(name="boom", version="0", settings={})

    def recognize_page(self, image: np.ndarray, page_number: int = 1) -> PageRecognition:
        raise RuntimeError("secret internal detail")


def test_a_corrupt_file_fails_cleanly_with_a_user_message(client):
    truncated = make_png()[:30]  # valid PNG signature, broken body: passes the upload check
    doc_id = _upload(client, truncated).json()["id"]

    assert client.app.state.worker.run_once() is True

    doc = client.get(f"/api/v1/documents/{doc_id}").json()
    assert doc["status"] == "failed" and doc["error_code"] == "corrupt"
    assert doc["error_message"] == "The file could not be read as an image."
    assert doc["latest_run"]["status"] == "failed"
    assert client.get(f"/api/v1/documents/{doc_id}/extraction").status_code == 409


def test_page_limit_is_enforced_by_the_worker(make_settings):
    with TestClient(create_app(make_settings(max_pages=2))) as c:
        doc_id = _upload(c, make_tiff(3), "scan.tif").json()["id"]
        c.app.state.worker.run_once()

        doc = c.get(f"/api/v1/documents/{doc_id}").json()

    assert doc["status"] == "failed" and doc["error_code"] == "too_many_pages"


def test_retry_queues_a_new_run_and_keeps_the_history(client):
    doc_id = _upload(client, make_png()[:30]).json()["id"]
    worker = client.app.state.worker
    worker.run_once()

    retried = client.post(f"/api/v1/documents/{doc_id}/retry")

    assert retried.status_code == 202
    body = retried.json()
    assert body["status"] == "uploaded" and body["error_code"] is None
    assert body["latest_run"]["status"] == "queued"

    worker.run_once()  # fails again (the file is still corrupt)
    with client.app.state.session_factory() as db:
        runs = db.scalars(select(ExtractionRun).order_by(ExtractionRun.created_at)).all()
    assert [r.status for r in runs] == ["failed", "failed"]  # earlier run is preserved


def test_unexpected_errors_do_not_leak_internals(client):
    doc_id = _upload(client, make_png()).json()["id"]
    app = client.app
    worker = JobWorker(app.state.session_factory, app.state.storage, BoomEngine(), app.state.settings)

    worker.run_once()

    doc = client.get(f"/api/v1/documents/{doc_id}").json()
    assert doc["status"] == "failed" and doc["error_code"] == "processing_error"
    assert "secret internal detail" not in str(doc)  # nothing internal in the API
    with app.state.session_factory() as db:
        run = db.scalars(select(ExtractionRun)).one()
    assert "secret internal detail" in run.error  # kept for developers


def test_a_run_is_claimed_only_once(client):
    _upload(client, make_png())
    worker = client.app.state.worker

    assert worker.run_once() is True
    assert worker.run_once() is False  # nothing left in the queue


def test_runs_are_processed_oldest_first(client):
    first = _upload(client, make_png(), "first.png").json()["id"]
    second = _upload(client, make_png(), "second.png").json()["id"]

    client.app.state.worker.run_once()

    assert client.get(f"/api/v1/documents/{first}").json()["status"] == "needs_review"
    assert client.get(f"/api/v1/documents/{second}").json()["status"] == "uploaded"


def test_interrupted_runs_are_requeued_and_complete_on_restart(client):
    doc_id = _upload(client, make_png()).json()["id"]
    worker = client.app.state.worker
    # Simulate a crash: the run was claimed and the document marked processing.
    assert worker._claim_next() is not None
    with client.app.state.session_factory() as db:
        db.get(Document, db.scalars(select(Document.id)).one()).status = "processing"
        db.commit()

    assert worker.recover_interrupted() == 1

    doc = client.get(f"/api/v1/documents/{doc_id}").json()
    assert doc["status"] == "uploaded" and doc["latest_run"]["status"] == "queued"
    assert worker.run_once() is True
    assert client.get(f"/api/v1/documents/{doc_id}").json()["status"] == "needs_review"


def test_pages_and_regions_are_stored_in_the_database(client):
    _upload(client, make_tiff(2), "scan.tif")
    client.app.state.worker.run_once()

    with client.app.state.session_factory() as db:
        pages = db.scalars(select(Page).order_by(Page.page_number)).all()
        regions = db.scalars(select(Region).order_by(Region.sequence)).all()

    assert [(p.page_number, p.width, p.height) for p in pages] == [(1, 200, 100), (2, 200, 100)]
    assert [r.provenance for r in regions] == ["replay", "replay"]
    assert regions[0].polygon == [[10, 20], [110, 20], [110, 40], [10, 40]]


def test_files_are_written_to_storage(client, tmp_path):
    doc_id = _upload(client, make_png()).json()["id"]
    client.app.state.worker.run_once()

    base = tmp_path / "store" / "documents" / doc_id
    assert (base / "original.png").is_file()
    assert (base / "pages" / "1.original.png").is_file()
    assert not (base / "pages" / "1.ocr.png").exists()  # replay never changes the image


def test_the_background_thread_processes_uploads_end_to_end(make_settings):
    settings = make_settings(run_worker=True, worker_poll_interval_s=0.05)
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/v1/health").json()["worker_running"] is True
        doc_id = _upload(c, make_png()).json()["id"]

        deadline = time.time() + 15
        status = None
        while time.time() < deadline:
            status = c.get(f"/api/v1/documents/{doc_id}").json()["status"]
            if status == "needs_review":
                break
            time.sleep(0.05)

        assert status == "needs_review"
        assert len(c.get(f"/api/v1/documents/{doc_id}/extraction").json()["regions"]) == 1