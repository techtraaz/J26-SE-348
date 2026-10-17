"""Documents API tests: upload -> queue -> (worker) -> status -> results.

The worker is driven by hand (worker.run_once()) so every state is
observable; the real background thread is covered in test_worker.py.
"""

import io
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import create_app
from tests.conftest import make_png, make_tiff

@pytest.fixture
def client(make_settings):
    with TestClient(create_app(make_settings())) as c:
        yield c

def _upload(client, data: bytes, name="invoice.png", **form):
    return client.post("/api/v1/documents", files={"file": (name, data)}, data=form)

def _process(client) -> bool:
    return client.app.state.worker.run_once()

def test_upload_returns_202_immediately_with_queued_state(client):
    response = _upload(client, make_png())

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "uploaded" and body["filename"] == "invoice.png"
    assert body["mime"] == "image/png" and body["source"] == "demo"
    assert body["latest_run"]["status"] == "queued"
    assert response.headers["location"] == f"/api/v1/documents/{body['id']}"

def test_full_flow_to_needs_review_with_regions(client):
    doc_id = _upload(client, make_png()).json()["id"]
    assert _process(client) is True

    doc = client.get(f"/api/v1/documents/{doc_id}").json()
    assert doc["status"] == "needs_review" and doc["page_count"] == 1
    assert doc["latest_run"]["status"] == "succeeded"
    assert doc["latest_run"]["engine"] == "replay"  # provenance is visible
    assert doc["latest_run"]["pages_done"] == doc["latest_run"]["pages_total"] == 1

    extraction = client.get(f"/api/v1/documents/{doc_id}/extraction").json()
    region = extraction["regions"][0]
    assert region["text"] == "TOTAL 42.00" and region["page_number"] == 1
    assert region["confidence"] == 0.9731  # raw score untouched
    assert region["box"] == [10, 20, 110, 40] and region["provenance"] == "replay"
    assert (extraction["pages"][0]["width"], extraction["pages"][0]["height"]) == (200, 100)

def test_page_images_are_served(client):
    doc_id = _upload(client, make_png()).json()["id"]
    _process(client)
    url = client.get(f"/api/v1/documents/{doc_id}/extraction").json()["pages"][0]["image_url"]

    for suffix in ("", "?variant=original"):
        image = client.get(url + suffix)
        assert image.status_code == 200 and image.headers["content-type"] == "image/png"
        assert Image.open(io.BytesIO(image.content)).size == (200, 100)

def test_multipage_tiff_gives_ordered_regions_across_pages(client):
    doc_id = _upload(client, make_tiff(3), "scan.tif").json()["id"]
    _process(client)

    extraction = client.get(f"/api/v1/documents/{doc_id}/extraction").json()
    assert [r["page_number"] for r in extraction["regions"]] == [1, 2, 3]
    assert [r["sequence"] for r in extraction["regions"]] == [0, 1, 2]
    assert len(extraction["pages"]) == 3

def test_extraction_is_409_until_the_run_succeeds(client):
    doc_id = _upload(client, make_png()).json()["id"]

    response = client.get(f"/api/v1/documents/{doc_id}/extraction")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "extraction_not_ready"

@pytest.mark.parametrize(
    "data, status, code",
    [
        (b"", 400, "empty_file"),
        (b"just some text", 415, "unsupported_type"),
    ],
)
def test_bad_uploads_are_rejected_immediately_and_create_nothing(client, data, status, code):
    response = _upload(client, data)

    assert response.status_code == status and response.json()["error"]["code"] == code
    assert client.get("/api/v1/documents").json()["total"] == 0

def test_oversized_upload_gets_413(make_settings):
    with TestClient(create_app(make_settings(max_file_bytes=100))) as c:
        response = _upload(c, make_png())

    assert response.status_code == 413 and response.json()["error"]["code"] == "too_large"

def test_a_path_in_the_filename_is_stripped(client):
    body = _upload(client, make_png(), "..\\..\\secret/evil.png").json()

    assert body["filename"] == "evil.png"

def test_list_filters_search_and_pagination(client):
    ids = [_upload(client, make_png(), f"doc{i}.png").json()["id"] for i in range(3)]
    _process(client)  # only the oldest run is processed

    assert client.get("/api/v1/documents").json()["total"] == 3
    assert client.get("/api/v1/documents?status=needs_review").json()["total"] == 1
    assert client.get("/api/v1/documents?status=uploaded").json()["total"] == 2
    assert [d["filename"] for d in client.get("/api/v1/documents?q=DOC2").json()["items"]] == ["doc2.png"]

    page = client.get("/api/v1/documents?limit=2&offset=0").json()
    assert len(page["items"]) == 2 and page["total"] == 3
    newest_first = [d["id"] for d in client.get("/api/v1/documents").json()["items"]]
    assert newest_first == ids[::-1]

def test_search_treats_wildcards_literally(client):
    _upload(client, make_png(), "plain.png")

    assert client.get("/api/v1/documents?q=%25").json()["total"] == 0  # "%" is not a wildcard

def test_upload_into_a_folder_and_unknown_folder(client, make_settings):
    missing = _upload(client, make_png(), folder_id=str(uuid.uuid4()))

    assert missing.status_code == 404 and missing.json()["error"]["code"] == "folder_not_found"

    factory = client.app.state.session_factory
    from app.db.models import Folder

    with factory() as db:
        folder = Folder(name="Invoices 2026")
        db.add(folder)
        db.commit()
        folder_id = str(folder.id)

    doc = _upload(client, make_png(), folder_id=folder_id).json()
    assert doc["folder_id"] == folder_id
    assert client.get(f"/api/v1/documents?folder_id={folder_id}").json()["total"] == 1

def test_source_tag_is_recorded(client):
    body = _upload(client, make_png(), source="research").json()

    assert body["source"] == "research"

def test_unknown_and_malformed_ids(client):
    unknown = client.get(f"/api/v1/documents/{uuid.uuid4()}")

    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "document_not_found"
    assert client.get("/api/v1/documents/not-a-uuid").status_code == 422
    doc_id = _upload(client, make_png()).json()["id"]
    _process(client)
    assert client.get(f"/api/v1/documents/{doc_id}/pages/9/image").status_code == 404

def test_retry_only_applies_to_failed_documents(client):
    doc_id = _upload(client, make_png()).json()["id"]

    response = client.post(f"/api/v1/documents/{doc_id}/retry")

    assert response.status_code == 409 and response.json()["error"]["code"] == "not_retryable"

def test_health_reports_engine_and_worker(client):
    body = client.get("/api/v1/health").json()

    assert body["status"] == "ok" and body["engine"] == "replay"
    assert body["worker_running"] is False  # worker is off in this fixture