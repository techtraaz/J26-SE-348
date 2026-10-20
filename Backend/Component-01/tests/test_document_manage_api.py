"""Managing documents: folder names in responses, rename, move, delete."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.enums import DocumentStatus
from app.db.models import Document, ExtractionRun, Page, ReviewDraft
from app.main import create_app
from tests.conftest import make_png


@pytest.fixture
def client(make_settings):
    with TestClient(create_app(make_settings())) as c:
        yield c


def _folder(client, name="Invoices 2025") -> str:
    return client.post("/api/v1/folders", json={"name": name}).json()["id"]


def _upload(client, folder_id: str | None = None, name="scan.png") -> str:
    data = {"folder_id": folder_id} if folder_id else {}
    return client.post("/api/v1/documents", files={"file": (name, make_png())}, data=data).json()["id"]


def _patch(client, doc_id, **body):
    return client.patch(f"/api/v1/documents/{doc_id}", json=body)


def _count(client, model) -> int:
    with client.app.state.session_factory() as db:
        return db.scalar(select(func.count()).select_from(model))


# ---- folder names ----------------------------------------------------------


def test_documents_carry_their_folder_name_and_unfiled_ones_none(client):
    folder = _folder(client)
    filed = _upload(client, folder, "march.png")
    unfiled = _upload(client, name="loose.png")

    items = {d["id"]: d for d in client.get("/api/v1/documents").json()["items"]}

    assert (items[filed]["folder_id"], items[filed]["folder_name"]) == (folder, "Invoices 2025")
    assert (items[unfiled]["folder_id"], items[unfiled]["folder_name"]) == (None, None)
    assert client.get(f"/api/v1/documents/{filed}").json()["folder_name"] == "Invoices 2025"


def test_unfiled_documents_are_the_root_only_listing(client):
    _upload(client, _folder(client))
    unfiled = _upload(client)

    listing = client.get("/api/v1/documents", params={"root_only": True}).json()

    assert [d["id"] for d in listing["items"]] == [unfiled]


# ---- rename and move -------------------------------------------------------


def test_rename_keeps_everything_else(client):
    folder = _folder(client)
    doc_id = _upload(client, folder, "IMG_0042.png")

    response = _patch(client, doc_id, filename="  March invoice.png  ")

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "March invoice.png"  # trimmed
    assert body["folder_id"] == folder  # not moved


def test_a_document_needs_a_name(client):
    doc_id = _upload(client)

    assert _patch(client, doc_id, filename="   ").status_code == 422
    assert _patch(client, doc_id, filename=None).status_code == 422
    assert _patch(client, doc_id, filename="x" * 256).status_code == 422


def test_move_into_a_folder_and_back_to_unfiled(client):
    folder = _folder(client)
    doc_id = _upload(client, name="loose.png")

    moved = _patch(client, doc_id, folder_id=folder).json()
    assert (moved["folder_id"], moved["folder_name"], moved["filename"]) == (folder, "Invoices 2025", "loose.png")

    unfiled = _patch(client, doc_id, folder_id=None).json()
    assert (unfiled["folder_id"], unfiled["folder_name"]) == (None, None)


def test_moving_to_an_unknown_folder_is_refused(client):
    doc_id = _upload(client)

    response = _patch(client, doc_id, folder_id=str(uuid.uuid4()))

    assert response.status_code == 404 and response.json()["error"]["code"] == "folder_not_found"
    assert client.get(f"/api/v1/documents/{doc_id}").json()["folder_id"] is None


def test_unknown_document(client):
    assert _patch(client, uuid.uuid4(), filename="x").status_code == 404
    assert client.delete(f"/api/v1/documents/{uuid.uuid4()}").status_code == 404


# ---- delete ----------------------------------------------------------------


def test_delete_removes_the_document_its_data_and_its_files(client):
    folder = _folder(client)
    doc_id = _upload(client, folder)
    assert client.app.state.worker.run_once() is True
    client.get(f"/api/v1/documents/{doc_id}/review")  # nothing saved by reading
    draft = client.get(f"/api/v1/documents/{doc_id}/review").json()
    keep = ("line_id", "region_id", "page", "sequence", "text", "box", "human_action")
    client.put(f"/api/v1/documents/{doc_id}/review", json={
        "version": 0, "based_on_run_id": draft["based_on_run_id"],
        "lines": [{k: line[k] for k in keep} for line in draft["lines"]],
    })
    storage = client.app.state.storage
    assert storage.exists(f"documents/{doc_id}/pages/1.original.png")

    response = client.delete(f"/api/v1/documents/{doc_id}")

    assert response.status_code == 204
    assert client.get(f"/api/v1/documents/{doc_id}").status_code == 404
    assert (_count(client, Document), _count(client, ExtractionRun), _count(client, Page), _count(client, ReviewDraft)) == (0, 0, 0, 0)
    assert not storage.exists(f"documents/{doc_id}/pages/1.original.png")
    assert not any(storage._path("documents").glob(f"{doc_id}*"))
    # Its folder is empty again, so it can be deleted.
    assert client.delete(f"/api/v1/folders/{folder}").status_code == 204


def test_a_queued_document_can_be_deleted(client):
    doc_id = _upload(client)  # not extracted yet

    assert client.delete(f"/api/v1/documents/{doc_id}").status_code == 204
    assert client.app.state.worker.run_once() is False  # nothing left to process


def test_a_verified_document_is_kept(client):
    doc_id = _upload(client)
    client.app.state.worker.run_once()
    assert client.post(f"/api/v1/documents/{doc_id}/confirm", json={"version": 0}).status_code == 201

    response = client.delete(f"/api/v1/documents/{doc_id}")

    assert response.status_code == 409 and response.json()["error"]["code"] == "document_verified"
    assert client.get(f"/api/v1/documents/{doc_id}").status_code == 200
    # Reopening does not make it deletable: its verified versions remain.
    client.post(f"/api/v1/documents/{doc_id}/reopen")
    assert client.delete(f"/api/v1/documents/{doc_id}").status_code == 409


def test_a_document_being_extracted_cannot_be_deleted(client):
    doc_id = _upload(client)
    with client.app.state.session_factory() as db:
        db.get(Document, uuid.UUID(doc_id)).status = DocumentStatus.PROCESSING.value
        db.commit()

    response = client.delete(f"/api/v1/documents/{doc_id}")

    assert response.status_code == 409 and response.json()["error"]["code"] == "document_busy"
