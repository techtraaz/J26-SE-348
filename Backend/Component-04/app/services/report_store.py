"""MongoDB access for the final audit report.

Reads Component-03's saved audit records (``c03_audit_results``, read-only)
and keeps every generated PDF in Component-04's own collection
(``c04_reports``) — the file itself is stored in MongoDB, nothing is written
to the local disk.

pymongo is synchronous, so every call runs in a worker thread
(``asyncio.to_thread``) and never blocks the event loop.
"""

from __future__ import annotations

import asyncio
import re
import threading
from typing import Any

from bson import Binary

from app import config

AUDIT_ID = re.compile(r"^[A-Za-z0-9._-]{1,120}:v\d{1,6}$")
REPORT_FILE = re.compile(r"^RPT-[A-Z0-9-]{1,80}\.pdf$")
MAX_PDF_BYTES = 15 * 1024 * 1024  # a MongoDB document holds at most 16 MB

_db: Any = None
_lock = threading.Lock()


class StoreUnavailable(RuntimeError):
    """MongoDB is not configured or cannot be reached."""


def use_database(db: Any) -> None:
    """Use this database (tests pass a mongomock one). None resets."""
    global _db
    _db = db


def _database() -> Any:
    global _db
    if _db is None:
        with _lock:
            if _db is None:
                if not config.MONGODB_URI:
                    raise StoreUnavailable("MongoDB is not configured (C04_MONGODB_URI)")
                from pymongo import MongoClient
                client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=8000,
                                     appname="nomos-c04-reports")
                _db = client[config.MONGODB_DB_NAME]
    return _db


async def _run(fn, *args):
    from pymongo.errors import PyMongoError
    try:
        return await asyncio.to_thread(fn, *args)
    except PyMongoError as exc:
        raise StoreUnavailable(f"MongoDB error: {exc}") from exc


# ── Audit records (Component-03, read-only) ───────────────────────────

def _get_audit(audit_id: str) -> dict | None:
    return _database()[config.AUDIT_RESULTS_COLLECTION].find_one({"_id": audit_id})


def _latest_audit(case_id: str) -> dict | None:
    return _database()[config.AUDIT_RESULTS_COLLECTION].find_one(
        {"case_id": case_id}, sort=[("version", -1)])


async def get_audit(audit_id: str) -> dict | None:
    return await _run(_get_audit, audit_id)


async def latest_audit(case_id: str) -> dict | None:
    return await _run(_latest_audit, case_id)


# ── Reports (Component-04) ────────────────────────────────────────────

_META = {"pdf": 0}  # listings never load the file itself


def _save_report(meta: dict, pdf: bytes) -> None:
    col = _database()[config.REPORTS_COLLECTION]
    col.create_index([("case_id", 1), ("generated_at", -1)])
    col.create_index("filename", unique=True)
    col.insert_one({**meta, "_id": meta["report_id"], "size_bytes": len(pdf),
                    "content_type": "application/pdf", "pdf": Binary(pdf)})


def _get_report(filename: str) -> dict | None:
    return _database()[config.REPORTS_COLLECTION].find_one({"filename": filename})


def _list_reports(case_id: str, limit: int) -> list[dict]:
    col = _database()[config.REPORTS_COLLECTION]
    return list(col.find({"case_id": case_id}, _META).sort("generated_at", -1).limit(limit))


async def save_report(meta: dict, pdf: bytes) -> None:
    if len(pdf) > MAX_PDF_BYTES:
        raise ValueError(f"The report is {len(pdf):,} bytes, over the {MAX_PDF_BYTES:,} byte limit.")
    await _run(_save_report, meta, pdf)


async def get_report(filename: str) -> dict | None:
    return await _run(_get_report, filename)


async def list_reports(case_id: str, limit: int = 50) -> list[dict]:
    return await _run(_list_reports, case_id, limit)
