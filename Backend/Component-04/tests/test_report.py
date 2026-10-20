"""Final audit report: C3's request -> saved audit -> PDF stored in MongoDB -> link.

Uses the five sample audits Component-03 saved (verdicts clean, needs_review
and issues_found), loaded into the in-memory MongoDB from conftest.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app import config
from app.main import app
from app.reporting.audit_report import build_audit_report

SAMPLES = json.loads((Path(__file__).parent / "fixtures" / "c03_audit_samples.json").read_text("utf-8"))
BY_ID = {s["_id"]: s for s in SAMPLES}
ISSUES = "CASE-SAMPLE-04:v1"   # POL-07 failed: one high finding
NOW = datetime(2026, 10, 21, 9, 30, tzinfo=UTC)


@pytest.fixture
def mongo(_in_memory_mongo):
    _in_memory_mongo[config.AUDIT_RESULTS_COLLECTION].insert_many(copy.deepcopy(SAMPLES))
    return _in_memory_mongo


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _text(record: dict) -> bytes:
    """The uncompressed PDF, so the text drawn on the pages can be searched."""
    return build_audit_report(record, report_id="RPT-20261021-093000-TEST", generated_at=NOW,
                              compress=False)


# ── The PDF ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("audit_id", sorted(BY_ID))
def test_every_sample_audit_makes_a_complete_report(audit_id):
    record = BY_ID[audit_id]
    pdf = _text(record)
    assert pdf.startswith(b"%PDF-")
    for section in (b"Executive summary", b"Scope and evidence", b"Detailed findings",
                    b"Recommendations", b"Auditor sign-off"):
        assert section in pdf, section
    assert record["case_id"].encode() in pdf
    assert b"RPT-20261021-093000-TEST" in pdf
    assert b"Page 1 of" in pdf


def test_report_shows_the_verdict_score_and_the_failed_rule():
    pdf = _text(BY_ID[ISSUES])
    assert b"Issues found" in pdf and b"75" in pdf
    assert b"POL-07" in pdf and b"FAILED" in pdf
    assert b"04_Tax_Invoice_COI-INV-26-1158.pdf" in pdf          # scope lists the document
    assert b"Get the missing approval signed before payment" in pdf  # C3's recommendation


def test_clean_audit_says_no_action_is_needed():
    pdf = _text(BY_ID["CASE-SAMPLE-01:v1"])
    assert b"Clean" in pdf and b"No corrective action is required" in pdf


def test_record_text_is_never_read_as_markup_and_odd_records_still_render():
    record = copy.deepcopy(BY_ID[ISSUES])
    record["narrative"] = "Totals <b>differ</b> & need <i>review</i> </para>"
    record["verdict"], record["score"] = "not_auditable", None
    record["case"]["docs"][0]["name"] = "A & B <draft>.pdf"
    pdf = _text(record)
    drawn = b"".join(re.findall(rb"\((.*?)\) Tj", pdf))  # the text pieces as drawn
    assert b"Not auditable" in pdf
    assert b"<b>differ</b> & need <i>review</i>" in drawn  # literal text, not bold/italic markup
    assert b"A & B <draft>.pdf" in drawn


# ── The pipeline (API) ─────────────────────────────────────────────────

async def test_generate_saves_the_pdf_in_mongodb_and_returns_the_agreed_reply(mongo, tmp_path,
                                                                              monkeypatch):
    monkeypatch.chdir(tmp_path)
    async with _client() as client:
        resp = await client.post("/report/generate",
                                 json={"audit_id": ISSUES, "case_id": "CASE-SAMPLE-04", "version": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "report_ready"                         # the contract's two fields
    assert body["download_url"] == f"/report/download/{body['filename']}"
    assert (body["audit_id"], body["verdict"], body["score"]) == (ISSUES, "issues_found", 75)

    saved = mongo[config.REPORTS_COLLECTION].find_one({"_id": body["report_id"]})
    assert bytes(saved["pdf"]).startswith(b"%PDF-") and saved["size_bytes"] == len(bytes(saved["pdf"]))
    assert not any(tmp_path.iterdir())  # nothing written to the local disk


async def test_download_serves_the_stored_pdf(mongo):
    async with _client() as client:
        made = (await client.post("/report/generate", json={"audit_id": ISSUES})).json()
        view = await client.get(made["download_url"])
        save = await client.get(made["download_url"], params={"download": 1})
    assert view.status_code == 200 and view.headers["content-type"] == "application/pdf"
    assert view.content.startswith(b"%PDF-")
    assert view.headers["content-disposition"].startswith("inline")
    assert save.headers["content-disposition"] == f'attachment; filename="{made["filename"]}"'


async def test_reports_of_a_case_are_listed_without_their_files(mongo):
    async with _client() as client:
        await client.post("/report/generate", json={"audit_id": ISSUES})
        await client.post("/report/generate", json={"case_id": "CASE-SAMPLE-04", "version": 1})
        listing = (await client.get("/report/list/CASE-SAMPLE-04")).json()
    assert len(listing["reports"]) == 2
    assert all("pdf" not in r and r["download_url"].startswith("/report/download/RPT-")
               for r in listing["reports"])


async def test_older_case_only_request_reports_the_latest_version(mongo):
    newer = copy.deepcopy(BY_ID[ISSUES])
    newer.update(_id="CASE-SAMPLE-04:v2", version=2, verdict="clean", score=100)
    mongo[config.AUDIT_RESULTS_COLLECTION].insert_one(newer)
    async with _client() as client:
        body = (await client.post("/report/generate/CASE-SAMPLE-04")).json()
    assert (body["audit_id"], body["version"]) == ("CASE-SAMPLE-04:v2", 2)


@pytest.mark.parametrize(("payload", "status", "words"), [
    ({"audit_id": "CASE-NOPE:v1"}, 404, "No saved audit"),
    ({"audit_id": "../../etc/passwd"}, 400, "Invalid audit id"),
    ({"audit_id": ISSUES, "case_id": "CASE-SAMPLE-04", "version": 2}, 400, "does not match"),
    ({}, 400, "Name the audit"),
])
async def test_bad_requests_get_a_detail_c3_can_show(mongo, payload, status, words):
    async with _client() as client:
        resp = await client.post("/report/generate", json=payload)
    assert resp.status_code == status and words in resp.json()["detail"]


async def test_records_of_another_schema_version_are_refused(mongo):
    future = copy.deepcopy(BY_ID[ISSUES])
    future.update(_id="CASE-FUTURE:v1", case_id="CASE-FUTURE", schema_version=2)
    mongo[config.AUDIT_RESULTS_COLLECTION].insert_one(future)
    async with _client() as client:
        resp = await client.post("/report/generate", json={"audit_id": "CASE-FUTURE:v1"})
    assert resp.status_code == 422 and "schema_version" in resp.json()["detail"]


async def test_unknown_or_unsafe_download_names_are_not_found(mongo):
    async with _client() as client:
        for name in ("RPT-20990101-000000-ZZZZ.pdf", "..%2F..%2Fsecret.pdf", "report.txt"):
            assert (await client.get(f"/report/download/{name}")).status_code == 404
