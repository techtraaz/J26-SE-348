import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_png

@pytest.fixture
def client(make_settings):
    with TestClient(create_app(make_settings())) as c:
        yield c

def _folder(client, name, parent_id=None):
    body = {"name": name, **({"parent_id": parent_id} if parent_id else {})}
    return client.post("/api/v1/folders", json=body)

def test_create_nested_folders_and_list_children(client):
    invoices = _folder(client, "Invoices").json()
    q1 = _folder(client, "Q1", invoices["id"])

    assert q1.status_code == 201 and q1.json()["parent_id"] == invoices["id"]
    assert q1.headers["location"] == f"/api/v1/folders/{q1.json()['id']}"

    root = client.get("/api/v1/folders").json()["items"]
    assert [f["name"] for f in root] == ["Invoices"]
    assert root[0]["folder_count"] == 1 and root[0]["document_count"] == 0

    children = client.get(f"/api/v1/folders?parent_id={invoices['id']}").json()["items"]
    assert [f["name"] for f in children] == ["Q1"]

def test_folders_are_listed_alphabetically_ignoring_case(client):
    for name in ("beta", "Alpha", "charlie"):
        _folder(client, name)

    assert [f["name"] for f in client.get("/api/v1/folders").json()["items"]] == ["Alpha", "beta", "charlie"]

def test_names_are_unique_per_parent_ignoring_case(client):
    parent = _folder(client, "Receipts").json()["id"]

    assert _folder(client, "receipts").status_code == 409
    assert _folder(client, "RECEIPTS").json()["error"]["code"] == "folder_exists"
    # The same name under a different parent is fine.
    assert _folder(client, "Receipts", parent).status_code == 201

def test_names_are_trimmed_and_must_not_be_blank(client):
    assert _folder(client, "  Padded  ").json()["name"] == "Padded"
    assert _folder(client, "   ").status_code == 422
    assert _folder(client, "x" * 256).status_code == 422

def test_unknown_parent_is_404(client):
    response = _folder(client, "Orphan", str(uuid.uuid4()))

    assert response.status_code == 404 and response.json()["error"]["code"] == "folder_not_found"
    assert client.get(f"/api/v1/folders?parent_id={uuid.uuid4()}").status_code == 404

def test_breadcrumbs_run_from_root_to_the_folder(client):
    a = _folder(client, "A").json()["id"]
    b = _folder(client, "B", a).json()["id"]
    c = _folder(client, "C", b).json()["id"]

    detail = client.get(f"/api/v1/folders/{c}").json()

    assert [x["name"] for x in detail["breadcrumbs"]] == ["A", "B", "C"]
    assert detail["name"] == "C" and detail["parent_id"] == b

def test_rename_checks_for_duplicates_but_allows_the_same_name(client):
    _folder(client, "Alpha")
    beta = _folder(client, "Beta").json()["id"]

    assert client.patch(f"/api/v1/folders/{beta}", json={"name": "alpha"}).status_code == 409
    renamed = client.patch(f"/api/v1/folders/{beta}", json={"name": "Beta"})  # unchanged name
    assert renamed.status_code == 200
    assert client.patch(f"/api/v1/folders/{beta}", json={"name": "Gamma"}).json()["name"] == "Gamma"

def test_only_empty_folders_can_be_deleted(client):
    parent = _folder(client, "Parent").json()["id"]
    child = _folder(client, "Child", parent).json()["id"]

    blocked = client.delete(f"/api/v1/folders/{parent}")
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "folder_not_empty"

    assert client.delete(f"/api/v1/folders/{child}").status_code == 204
    assert client.delete(f"/api/v1/folders/{parent}").status_code == 204
    assert client.get(f"/api/v1/folders/{parent}").status_code == 404

def test_a_folder_with_documents_cannot_be_deleted_and_counts_them(client):
    folder = _folder(client, "Scans").json()["id"]
    client.post("/api/v1/documents", files={"file": ("a.png", make_png())}, data={"folder_id": folder})

    assert client.get("/api/v1/folders").json()["items"][0]["document_count"] == 1
    assert client.delete(f"/api/v1/folders/{folder}").status_code == 409

def test_root_only_filter_excludes_documents_in_folders(client):
    folder = _folder(client, "Scans").json()["id"]
    client.post("/api/v1/documents", files={"file": ("in.png", make_png())}, data={"folder_id": folder})
    client.post("/api/v1/documents", files={"file": ("root.png", make_png())})

    everything = client.get("/api/v1/documents").json()
    root = client.get("/api/v1/documents?root_only=true").json()
    inside = client.get(f"/api/v1/documents?folder_id={folder}").json()

    assert everything["total"] == 2
    assert [d["filename"] for d in root["items"]] == ["root.png"]
    assert [d["filename"] for d in inside["items"]] == ["in.png"]