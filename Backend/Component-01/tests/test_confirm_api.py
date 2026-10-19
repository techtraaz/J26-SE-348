"""Confirmation and verified versions (M5): confirm, reopen, read versions,
and the corrections log."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Correction
from app.main import create_app
from tests.conftest import make_png, make_tiff

# C3's contract line (Backend/Component-03/docs/c1_verified_record_contract.md).
CONTRACT_LINE_KEYS = {
    "line_id", "page", "sequence", "text", "confidence", "box", "provenance", "escalated", "human_action",
}
CONTRACT_KEYS = {"document_id", "version", "based_on_run_id", "confirmed_by", "confirmed_at", "lines"}


@pytest.fixture
def client(make_settings):
    with TestClient(create_app(make_settings())) as c:
        yield c


def _document(client) -> str:
    """Extracted, two pages, one region each ("TOTAL 42.00", box [10, 20, 110, 40])."""
    doc_id = client.post("/api/v1/documents", files={"file": ("scan.tif", make_tiff(2))}).json()["id"]
    assert client.app.state.worker.run_once() is True
    return doc_id


def _draft(client, doc_id):
    return client.get(f"/api/v1/documents/{doc_id}/review").json()


def _editable(lines):
    keep = ("line_id", "region_id", "page", "sequence", "text", "box", "human_action")
    return [{k: line[k] for k in keep} for line in lines]


def _save(client, doc_id, draft, lines):
    body = {"version": draft["version"], "based_on_run_id": draft["based_on_run_id"], "lines": lines}
    response = client.put(f"/api/v1/documents/{doc_id}/review", json=body)
    assert response.status_code == 200, response.json()
    return response.json()


def _confirm(client, doc_id, version):
    return client.post(f"/api/v1/documents/{doc_id}/confirm", json={"version": version})


def _corrections(client, doc_id) -> list[Correction]:
    with client.app.state.session_factory() as db:
        return list(
            db.scalars(
                select(Correction)
                .where(Correction.document_id == uuid.UUID(doc_id))
                .order_by(Correction.verified_version, Correction.action)
            )
        )


def _error(response):
    return response.json()["error"]["code"]


# ---- confirm ---------------------------------------------------------------


def test_confirming_a_never_saved_draft_accepts_every_line(client):
    doc_id = _document(client)

    response = _confirm(client, doc_id, 0)

    assert response.status_code == 201
    record = response.json()
    assert record["version"] == 1 and record["confirmed_by"] is None
    assert [line["human_action"] for line in record["lines"]] == ["accepted", "accepted"]
    assert record["lines"][0]["confidence"] == 0.9731  # raw machine score kept
    assert client.get(f"/api/v1/documents/{doc_id}").json()["status"] == "verified"
    corrections = _corrections(client, doc_id)
    assert [(c.action, c.verified_version, c.source) for c in corrections] == [("accept", 1, "demo")] * 2


def test_the_record_has_exactly_the_contract_shape(client):
    doc_id = _document(client)
    _confirm(client, doc_id, 0)

    record = client.get(f"/api/v1/documents/{doc_id}/verified").json()

    assert set(record) == CONTRACT_KEYS
    assert all(set(line) == CONTRACT_LINE_KEYS for line in record["lines"])
    assert record["document_id"] == doc_id


def test_edits_deletions_and_additions_are_recorded_and_logged(client):
    doc_id = _document(client)
    draft = _draft(client, doc_id)
    lines = _editable(draft["lines"])
    lines[0]["text"] = "TOTAL 42.50"
    lines[1]["human_action"] = "deleted"
    added_id = str(uuid.uuid4())
    lines.append({"line_id": added_id, "region_id": None, "page": 1, "sequence": 0,
                  "text": "VAT 6.30", "box": [10, 50, 90, 70], "human_action": "added"})
    saved = _save(client, doc_id, draft, lines)

    record = _confirm(client, doc_id, saved["version"]).json()

    assert [(line["text"], line["human_action"]) for line in record["lines"]] == [
        ("TOTAL 42.50", "edited"),
        ("VAT 6.30", "added"),  # the deleted line is left out
    ]
    added = record["lines"][1]
    assert added["line_id"] == added_id and added["provenance"] == "human" and added["confidence"] is None

    logged = {(c.action, c.after.get("line_id")): c for c in _corrections(client, doc_id)}
    edit = logged[("edit_text", lines[0]["line_id"])]
    assert (edit.before, edit.after["text"]) == ({"text": "TOTAL 42.00"}, "TOTAL 42.50")
    assert str(edit.region_id) == lines[0]["line_id"]
    assert logged[("delete", lines[1]["line_id"])].before == {"text": "TOTAL 42.00", "box": [10, 20, 110, 40]}
    assert logged[("add", added_id)].region_id is None
    assert len(logged) == 3  # no "accept" for edited, deleted or added lines


def test_a_moved_box_is_logged(client):
    doc_id = _document(client)
    draft = _draft(client, doc_id)
    lines = _editable(draft["lines"])
    lines[0]["box"] = [12, 20, 112, 40]
    saved = _save(client, doc_id, draft, lines)

    _confirm(client, doc_id, saved["version"])

    moves = [c for c in _corrections(client, doc_id) if c.action == "move_box"]
    assert [(m.before, m.after["box"]) for m in moves] == [({"box": [10, 20, 110, 40]}, [12, 20, 112, 40])]


# ---- refusals --------------------------------------------------------------


def test_a_stale_version_cannot_be_confirmed(client):
    doc_id = _document(client)
    draft = _draft(client, doc_id)
    _save(client, doc_id, draft, _editable(draft["lines"]))  # now version 1

    response = _confirm(client, doc_id, 0)

    assert response.status_code == 409 and _error(response) == "draft_conflict"
    assert client.get(f"/api/v1/documents/{doc_id}").json()["status"] == "needs_review"
    assert _corrections(client, doc_id) == []  # nothing written


def test_a_verified_document_cannot_be_confirmed_or_edited_again(client):
    doc_id = _document(client)
    _confirm(client, doc_id, 0)
    draft = _draft(client, doc_id)

    again = _confirm(client, doc_id, draft["version"])
    edit = client.put(f"/api/v1/documents/{doc_id}/review",
                      json={"version": draft["version"], "based_on_run_id": draft["based_on_run_id"],
                            "lines": _editable(draft["lines"])})

    assert again.status_code == 409 and _error(again) == "already_verified"
    assert edit.status_code == 409 and _error(edit) == "document_verified"


def test_nothing_can_be_confirmed_before_extraction(client):
    doc_id = client.post("/api/v1/documents", files={"file": ("a.png", make_png())}).json()["id"]

    response = _confirm(client, doc_id, 0)

    assert response.status_code == 409 and _error(response) == "extraction_not_ready"
    assert _confirm(client, uuid.uuid4(), 0).status_code == 404


def test_reading_a_missing_record(client):
    doc_id = _document(client)

    missing = client.get(f"/api/v1/documents/{doc_id}/verified")
    _confirm(client, doc_id, 0)
    no_version = client.get(f"/api/v1/documents/{doc_id}/verified/9")

    assert missing.status_code == 404 and _error(missing) == "not_verified"
    assert no_version.status_code == 404 and _error(no_version) == "version_not_found"


def test_only_a_verified_document_can_be_reopened(client):
    doc_id = _document(client)

    response = client.post(f"/api/v1/documents/{doc_id}/reopen")

    assert response.status_code == 409 and _error(response) == "not_reopenable"


# ---- versions --------------------------------------------------------------


def test_reopen_edit_and_confirm_again_makes_version_2_and_keeps_version_1(client):
    doc_id = _document(client)
    draft = _draft(client, doc_id)
    lines = _editable(draft["lines"])
    lines[1]["human_action"] = "deleted"
    _confirm(client, doc_id, _save(client, doc_id, draft, lines)["version"])

    assert client.post(f"/api/v1/documents/{doc_id}/reopen").status_code == 204
    assert client.get(f"/api/v1/documents/{doc_id}").json()["status"] == "needs_review"
    reopened = _draft(client, doc_id)
    # The draft continues from the confirmed state: the untouched line was accepted.
    assert [line["human_action"] for line in reopened["lines"]] == ["accepted", "deleted"]

    lines = _editable(reopened["lines"])
    lines[0]["text"] = "TOTAL 99.00"
    lines[1]["human_action"] = "untouched"  # restore the deleted line
    record = _confirm(client, doc_id, _save(client, doc_id, reopened, lines)["version"]).json()

    assert record["version"] == 2
    assert [(line["text"], line["human_action"]) for line in record["lines"]] == [
        ("TOTAL 99.00", "edited"),
        ("TOTAL 42.00", "accepted"),  # restored, then accepted on confirm
    ]
    v1 = client.get(f"/api/v1/documents/{doc_id}/verified/1").json()
    assert v1["version"] == 1 and [line["text"] for line in v1["lines"]] == ["TOTAL 42.00"]
    assert client.get(f"/api/v1/documents/{doc_id}/verified").json()["version"] == 2

    # Version 2 logs only what changed since version 1. The restored line was
    # already reviewed in version 1, so its restore is the one entry (no extra accept).
    v2_actions = sorted(c.action for c in _corrections(client, doc_id) if c.verified_version == 2)
    assert v2_actions == ["edit_text", "restore"]
