"""Review drafts API (M4): seed, save, reload, and the rules that keep a draft
an honest record of human review."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.enums import DocumentStatus
from app.db.models import Document
from app.main import create_app
from tests.conftest import make_png, make_tiff


@pytest.fixture
def client(make_settings):
    with TestClient(create_app(make_settings())) as c:
        yield c


def _document(client, data: bytes | None = None, name="scan.tif") -> str:
    """An extracted document. The replay fixture gives one 200x100 page with
    one region ("TOTAL 42.00", box [10, 20, 110, 40]) per page."""
    doc_id = client.post(
        "/api/v1/documents", files={"file": (name, data or make_tiff(2))}
    ).json()["id"]
    assert client.app.state.worker.run_once() is True
    return doc_id


def _review(client, doc_id):
    return client.get(f"/api/v1/documents/{doc_id}/review")


def _save(client, doc_id, draft, lines=None, **overrides):
    body = {
        "version": draft["version"],
        "based_on_run_id": draft["based_on_run_id"],
        "lines": lines if lines is not None else _editable(draft["lines"]),
    }
    body.update(overrides)
    return client.put(f"/api/v1/documents/{doc_id}/review", json=body)


def _editable(lines):
    """What the client sends: everything except the machine fields."""
    keep = ("line_id", "region_id", "page", "sequence", "text", "box", "human_action")
    return [{k: line[k] for k in keep} for line in lines]


def _error(response):
    return response.json()["error"]["code"]


# ---- seed and read ---------------------------------------------------------


def test_a_new_draft_is_seeded_from_the_run_and_not_stored(client):
    doc_id = _document(client)

    draft = _review(client, doc_id).json()

    assert draft["version"] == 0 and draft["updated_at"] is None
    regions = client.get(f"/api/v1/documents/{doc_id}/extraction").json()["regions"]
    assert [line["line_id"] for line in draft["lines"]] == [r["id"] for r in regions]
    first = draft["lines"][0]
    assert first["region_id"] == first["line_id"]
    assert (first["page"], first["sequence"], first["text"]) == (1, 0, "TOTAL 42.00")
    assert first["box"] == [10, 20, 110, 40]
    assert first["confidence"] == 0.9731  # raw score copied untouched (D4)
    assert first["provenance"] == "replay" and first["human_action"] == "untouched"
    assert _review(client, doc_id).json()["version"] == 0  # reading stores nothing


def test_review_is_409_before_extraction_and_404_for_unknown_documents(client):
    doc_id = client.post("/api/v1/documents", files={"file": ("a.png", make_png())}).json()["id"]

    assert _error(_review(client, doc_id)) == "extraction_not_ready"
    assert _review(client, doc_id).status_code == 409
    assert _review(client, uuid.uuid4()).status_code == 404


# ---- save and reload -------------------------------------------------------


def test_an_edit_persists_and_the_machine_output_is_untouched(client):
    doc_id = _document(client)
    draft = _review(client, doc_id).json()
    lines = _editable(draft["lines"])
    lines[0]["text"] = "TOTAL 42.50"
    lines[1]["human_action"] = "accepted"

    saved = _save(client, doc_id, draft, lines)

    assert saved.status_code == 200
    assert saved.json()["version"] == 1 and saved.json()["updated_at"] is not None
    reloaded = _review(client, doc_id).json()
    assert reloaded["version"] == 1
    assert reloaded["lines"][0]["text"] == "TOTAL 42.50"
    assert reloaded["lines"][0]["human_action"] == "edited"
    assert reloaded["lines"][1]["human_action"] == "accepted"
    regions = client.get(f"/api/v1/documents/{doc_id}/extraction").json()["regions"]
    assert regions[0]["text"] == "TOTAL 42.00"  # machine output never edited (D2)


def test_versions_advance_with_each_save(client):
    doc_id = _document(client)
    draft = _review(client, doc_id).json()

    first = _save(client, doc_id, draft).json()
    second = _save(client, doc_id, first).json()

    assert (first["version"], second["version"]) == (1, 2)


def test_a_stale_version_is_rejected(client):
    doc_id = _document(client)
    draft = _review(client, doc_id).json()
    assert _save(client, doc_id, draft).status_code == 200

    stale = _save(client, doc_id, draft)  # still based on version 0

    assert stale.status_code == 409 and _error(stale) == "draft_conflict"


def test_a_first_save_must_be_based_on_version_0(client):
    doc_id = _document(client)
    draft = _review(client, doc_id).json()

    response = _save(client, doc_id, draft, version=3)

    assert response.status_code == 409 and _error(response) == "draft_conflict"


def test_a_save_for_another_run_is_rejected(client):
    doc_id = _document(client)
    draft = _review(client, doc_id).json()

    response = _save(client, doc_id, draft, based_on_run_id=str(uuid.uuid4()))

    assert response.status_code == 409 and _error(response) == "run_changed"


def test_a_verified_document_cannot_be_edited(client):
    doc_id = _document(client)
    draft = _review(client, doc_id).json()
    with client.app.state.session_factory() as db:
        db.get(Document, uuid.UUID(doc_id)).status = DocumentStatus.VERIFIED.value
        db.commit()

    response = _save(client, doc_id, draft)

    assert response.status_code == 409 and _error(response) == "document_verified"


# ---- the server decides what happened --------------------------------------


def test_machine_fields_from_the_client_are_ignored(client):
    doc_id = _document(client)
    draft = _review(client, doc_id).json()
    lines = _editable(draft["lines"])
    lines[0].update(confidence=0.01, provenance="human", escalated=True)

    saved = _save(client, doc_id, draft, lines).json()

    assert saved["lines"][0]["confidence"] == 0.9731
    assert saved["lines"][0]["provenance"] == "replay"
    assert saved["lines"][0]["escalated"] is None


def test_a_changed_line_is_edited_whatever_the_client_calls_it(client):
    doc_id = _document(client)
    draft = _review(client, doc_id).json()
    lines = _editable(draft["lines"])
    lines[0]["text"] = "TOTAL 24.00"  # still "untouched" in the request
    lines[1]["box"] = [12, 20, 112, 40]

    saved = _save(client, doc_id, draft, lines).json()

    assert [line["human_action"] for line in saved["lines"]] == ["edited", "edited"]


def test_an_edit_changed_back_counts_as_accepted(client):
    doc_id = _document(client)
    draft = _review(client, doc_id).json()
    lines = _editable(draft["lines"])
    lines[0]["human_action"] = "edited"  # text is the machine's again

    saved = _save(client, doc_id, draft, lines).json()

    assert saved["lines"][0]["human_action"] == "accepted"


# ---- deleted and added lines -----------------------------------------------


def test_a_deleted_line_stays_in_the_draft(client):
    doc_id = _document(client)
    draft = _review(client, doc_id).json()
    lines = _editable(draft["lines"])
    lines[1]["human_action"] = "deleted"

    saved = _save(client, doc_id, draft, lines).json()

    assert len(saved["lines"]) == 2 and saved["lines"][1]["human_action"] == "deleted"


def test_a_machine_line_cannot_be_left_out(client):
    doc_id = _document(client)
    draft = _review(client, doc_id).json()

    response = _save(client, doc_id, draft, _editable(draft["lines"])[:1])

    assert response.status_code == 422 and _error(response) == "invalid_draft"
    assert "deleted" in response.json()["error"]["message"]


def test_an_added_line_is_marked_human_and_placed_in_reading_order(client):
    doc_id = _document(client)
    draft = _review(client, doc_id).json()
    lines = _editable(draft["lines"])
    added_id = str(uuid.uuid4())
    # Between the two machine lines: equal sequence sorts after the line sent first.
    lines.append({"line_id": added_id, "region_id": None, "page": 1, "sequence": 0,
                  "text": "VAT 6.30", "box": [10, 50, 90, 70], "human_action": "added"})

    saved = _save(client, doc_id, draft, lines).json()

    assert [line["sequence"] for line in saved["lines"]] == [0, 1, 2]
    added = saved["lines"][1]
    assert added["line_id"] == added_id and added["text"] == "VAT 6.30"
    assert added["confidence"] is None and added["provenance"] == "human"
    assert added["human_action"] == "added"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"box": [150, 50, 250, 70]}, "not inside page"),  # page is 200 wide
        ({"box": [90, 50, 10, 70]}, "not inside page"),  # x2 before x1
        ({"page": 9}, "no page 9"),
        ({"human_action": "untouched"}, "must be added"),
    ],
)
def test_invalid_added_lines_are_rejected(client, change, message):
    doc_id = _document(client)
    draft = _review(client, doc_id).json()
    added = {"line_id": str(uuid.uuid4()), "region_id": None, "page": 1, "sequence": 5,
             "text": "x", "box": [10, 50, 90, 70], "human_action": "added"}
    added.update(change)

    response = _save(client, doc_id, draft, _editable(draft["lines"]) + [added])

    assert response.status_code == 422 and message in response.json()["error"]["message"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"page": 2}, "cannot change page"),
        ({"human_action": "added"}, "cannot be 'added'"),
        ({"line_id": "00000000-0000-0000-0000-000000000001"}, "keeps its region's id"),
        ({"region_id": "00000000-0000-0000-0000-000000000001"}, "not in this run"),
    ],
)
def test_invalid_machine_lines_are_rejected(client, change, message):
    doc_id = _document(client)
    draft = _review(client, doc_id).json()
    lines = _editable(draft["lines"])
    lines[0].update(change)

    response = _save(client, doc_id, draft, lines)

    assert response.status_code == 422 and message in response.json()["error"]["message"]


def test_duplicate_lines_are_rejected(client):
    doc_id = _document(client)
    draft = _review(client, doc_id).json()
    lines = _editable(draft["lines"])

    response = _save(client, doc_id, draft, lines + [lines[0]])

    assert response.status_code == 422 and "more than once" in response.json()["error"]["message"]
