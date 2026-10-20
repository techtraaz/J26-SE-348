"""Export API (M5): verified records as JSON (contract 0.1) and CSV."""

import csv
import io

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_tiff


@pytest.fixture
def client(make_settings):
    with TestClient(create_app(make_settings())) as c:
        yield c


def _verified(client, text: str | None = None) -> str:
    """A confirmed document (two lines); optionally with line 1's text changed first."""
    doc_id = client.post("/api/v1/documents", files={"file": ("scan 7.tif", make_tiff(2))}).json()["id"]
    assert client.app.state.worker.run_once() is True
    draft = client.get(f"/api/v1/documents/{doc_id}/review").json()
    version = 0
    if text is not None:
        keep = ("line_id", "region_id", "page", "sequence", "text", "box", "human_action")
        lines = [{k: line[k] for k in keep} for line in draft["lines"]]
        lines[0]["text"] = text
        body = {"version": 0, "based_on_run_id": draft["based_on_run_id"], "lines": lines}
        version = client.put(f"/api/v1/documents/{doc_id}/review", json=body).json()["version"]
    assert client.post(f"/api/v1/documents/{doc_id}/confirm", json={"version": version}).status_code == 201
    return doc_id


def test_json_is_the_verified_record_with_its_schema_version(client):
    doc_id = _verified(client)

    response = client.get(f"/api/v1/documents/{doc_id}/export")

    assert response.headers["content-type"] == "application/json"
    assert response.headers["content-disposition"] == 'attachment; filename="scan 7-v1.json"'
    body = response.json()
    assert body.pop("schema_version") == "0.1"
    assert body == client.get(f"/api/v1/documents/{doc_id}/verified").json()


def test_csv_has_one_row_per_line_and_keeps_utf8_text(client):
    doc_id = _verified(client, text="RÉPORTING PERIODS: £12")

    response = client.get(f"/api/v1/documents/{doc_id}/export", params={"format": "csv"})

    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"].endswith('filename="scan 7-v1.csv"')
    text = response.content.decode("utf-8")
    assert text.startswith("﻿")  # so spreadsheets read the UTF-8 correctly
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    assert len(rows) == 2
    assert rows[0]["text"] == "RÉPORTING PERIODS: £12" and rows[0]["human_action"] == "edited"
    assert (rows[0]["x1"], rows[0]["y1"], rows[0]["x2"], rows[0]["y2"]) == ("10", "20", "110", "40")
    assert rows[1]["confidence"] == "0.9731" and rows[1]["escalated"] == ""


def test_a_given_version_can_be_exported(client):
    doc_id = _verified(client)
    client.post(f"/api/v1/documents/{doc_id}/reopen")
    draft = client.get(f"/api/v1/documents/{doc_id}/review").json()
    client.post(f"/api/v1/documents/{doc_id}/confirm", json={"version": draft["version"]})

    latest = client.get(f"/api/v1/documents/{doc_id}/export").json()
    first = client.get(f"/api/v1/documents/{doc_id}/export", params={"version": 1})

    assert latest["version"] == 2
    assert first.json()["version"] == 1
    assert first.headers["content-disposition"].endswith('-v1.json"')


def test_nothing_to_export_before_confirmation(client):
    doc_id = client.post("/api/v1/documents", files={"file": ("a.tif", make_tiff(1))}).json()["id"]
    client.app.state.worker.run_once()

    response = client.get(f"/api/v1/documents/{doc_id}/export")

    assert response.status_code == 404 and response.json()["error"]["code"] == "not_verified"
    assert client.get(f"/api/v1/documents/{doc_id}/export", params={"format": "xml"}).status_code == 422
