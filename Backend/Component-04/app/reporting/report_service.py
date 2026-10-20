"""Final report pipeline: audit id -> saved audit record -> PDF -> object storage.

Component-03 asks for a report when the user tells the Copilot to "generate
the report" (contract: Component-03/docs/c4_report_contract.md):

    POST /report/generate  {"audit_id": "<case_id>:v<version>", "case_id": ..., "version": ...}

C04 reads exactly that saved record, builds the PDF, uploads the file to the
project's S3-compatible object storage (indexed in MongoDB) and replies with
the download link, which C04 itself serves:

    {"status": "report_ready", "download_url": "/report/download/<file>.pdf", ...}

Errors are raised as ReportError(status, detail); the API turns them into
{"detail": "..."} replies, which C3 shows to the user.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import string
from datetime import UTC, datetime

from app.reporting.audit_report import build_audit_report
from app.services import report_store

logger = logging.getLogger("c04.report")

SUPPORTED_SCHEMA = 1


class ReportError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def _report_id(now: datetime) -> str:
    """RPT-20261021-093015-K7Q2: readable, sortable, unique enough per second."""
    suffix = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
    return f"RPT-{now:%Y%m%d-%H%M%S}-{suffix}"


async def _find_record(audit_id: str | None, case_id: str | None, version: int | None) -> dict:
    """The saved audit the request names. Validates the ids before any lookup."""
    if audit_id is None and case_id and version is not None:
        audit_id = f"{case_id}:v{version}"
    if audit_id is not None:
        if not report_store.AUDIT_ID.match(audit_id):
            raise ReportError(400, f"Invalid audit id {audit_id!r}; expected '<case_id>:v<version>'.")
        expected = f"{case_id}:v{version}" if case_id and version is not None else None
        if expected and expected != audit_id:
            raise ReportError(400, f"audit_id {audit_id!r} does not match case_id and version ({expected}).")
        record = await report_store.get_audit(audit_id)
        if record is None:
            raise ReportError(404, f"No saved audit {audit_id}. Run the audit first.")
        return record
    if case_id:
        if not report_store.AUDIT_ID.match(f"{case_id}:v1"):
            raise ReportError(400, f"Invalid case id {case_id!r}.")
        record = await report_store.latest_audit(case_id)
        if record is None:
            raise ReportError(404, f"No saved audit for case {case_id}. Run the audit first.")
        return record
    raise ReportError(400, "Name the audit: send audit_id, or case_id and version.")


async def generate(audit_id: str | None = None, case_id: str | None = None,
                   version: int | None = None) -> dict:
    try:
        record = await _find_record(audit_id, case_id, version)
        if record.get("schema_version") != SUPPORTED_SCHEMA:
            raise ReportError(422, f"Audit record {record.get('_id')} has schema_version "
                                   f"{record.get('schema_version')!r}; this report supports "
                                   f"{SUPPORTED_SCHEMA}. Re-run the audit to refresh it.")
        now = datetime.now(UTC)
        report_id = _report_id(now)
        # building the PDF is CPU work: keep it off the event loop
        pdf = await asyncio.to_thread(build_audit_report, record, report_id=report_id, generated_at=now)
        meta = {
            "report_id": report_id, "filename": f"{report_id}.pdf",
            "audit_id": record["_id"], "case_id": record.get("case_id"), "version": record.get("version"),
            "verdict": record.get("verdict"), "score": record.get("score"),
            "generated_at": now.isoformat(), "sha256": hashlib.sha256(pdf).hexdigest(),
        }
        await report_store.save_report(meta, pdf)
    except report_store.StoreUnavailable as exc:
        raise ReportError(503, f"The report store is unavailable: {exc}") from exc
    except ValueError as exc:  # e.g. over the size limit
        raise ReportError(422, str(exc)) from exc

    logger.info("Report %s ready for %s (%d bytes)", report_id, meta["audit_id"], len(pdf))
    return {"status": "report_ready", **{k: v for k, v in meta.items() if k != "sha256"},
            "size_bytes": len(pdf), "download_url": f"/report/download/{meta['filename']}"}
