"""Storage for the final audit report.

- Audit records: read from Component-03's ``c03_audit_results`` (read-only).
- PDF files: uploaded to the project's S3-compatible object storage (Garage),
  under ``c04-reports/<case_id>/<report_id>.pdf`` in the shared bucket.
- Report index: one small row per report in C04's ``c04_reports`` collection
  (case, version, verdict, score, object key — never the file), so a case's
  reports can be listed without reading every object.

Reports made before the move to object storage kept their file in the index
row (``pdf``); they are still served from there.

pymongo and boto3 are synchronous, so every call runs in a worker thread
(``asyncio.to_thread``) and never blocks the event loop.
"""

from __future__ import annotations

import asyncio
import re
import threading
from collections.abc import Iterator
from typing import Any

from app import config

AUDIT_ID = re.compile(r"^[A-Za-z0-9._-]{1,120}:v\d{1,6}$")
REPORT_FILE = re.compile(r"^RPT-[A-Z0-9-]{1,80}\.pdf$")
MAX_PDF_BYTES = 50 * 1024 * 1024
CHUNK = 64 * 1024

_db: Any = None
_s3: Any = None
_bucket: str | None = None
_lock = threading.Lock()


class StoreUnavailable(RuntimeError):
    """MongoDB or the object storage is not configured or cannot be reached."""


# ── Connections ────────────────────────────────────────────────────────

def use_database(db: Any) -> None:
    """Use this database (tests pass a mongomock one). None resets."""
    global _db
    _db = db


def use_object_storage(client: Any, bucket: str | None = None) -> None:
    """Use this S3 client and bucket (tests pass a moto one). None resets."""
    global _s3, _bucket
    _s3, _bucket = client, bucket


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


def _storage() -> tuple[Any, str]:
    global _s3, _bucket
    if _s3 is None:
        with _lock:
            if _s3 is None:
                if not (config.GARAGE_ENDPOINT and config.GARAGE_ACCESS_KEY and config.GARAGE_SECRET_KEY):
                    raise StoreUnavailable("Object storage is not configured (GARAGE_ENDPOINT, "
                                           "GARAGE_ACCESS_KEY, GARAGE_SECRET_KEY)")
                import boto3
                from botocore.config import Config
                _s3 = boto3.client(
                    "s3",
                    endpoint_url=config.GARAGE_ENDPOINT,
                    aws_access_key_id=config.GARAGE_ACCESS_KEY,
                    aws_secret_access_key=config.GARAGE_SECRET_KEY,
                    region_name="garage",
                    config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                                  connect_timeout=10, read_timeout=60, retries={"max_attempts": 3}),
                )
                _bucket = config.GARAGE_BUCKET
    return _s3, _bucket or config.GARAGE_BUCKET


async def _run(fn, *args):
    from botocore.exceptions import BotoCoreError, ClientError
    from pymongo.errors import PyMongoError
    try:
        return await asyncio.to_thread(fn, *args)
    except PyMongoError as exc:
        raise StoreUnavailable(f"MongoDB error: {exc}") from exc
    except (BotoCoreError, ClientError) as exc:
        raise StoreUnavailable(f"Object storage error: {type(exc).__name__}") from exc


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


# ── Reports ────────────────────────────────────────────────────────────

def object_key(case_id: str, filename: str) -> str:
    return f"{config.REPORTS_PREFIX}/{case_id}/{filename}"


def _save_report(meta: dict, pdf: bytes) -> dict:
    s3, bucket = _storage()
    key = object_key(meta["case_id"], meta["filename"])
    s3.put_object(Bucket=bucket, Key=key, Body=pdf, ContentType="application/pdf",
                  Metadata={"report-id": meta["report_id"], "audit-id": meta["audit_id"],
                            "sha256": meta["sha256"]})
    row = {**meta, "_id": meta["report_id"], "storage": "object", "bucket": bucket,
           "object_key": key, "size_bytes": len(pdf), "content_type": "application/pdf"}
    col = _database()[config.REPORTS_COLLECTION]
    try:
        col.create_index([("case_id", 1), ("generated_at", -1)])
        col.create_index("filename", unique=True)
        col.insert_one(row)
    except Exception:
        # no index row means nobody can find the file: do not leave it behind
        s3.delete_object(Bucket=bucket, Key=key)
        raise
    return row


def _get_report(filename: str) -> dict | None:
    return _database()[config.REPORTS_COLLECTION].find_one({"filename": filename})


def _open_object(bucket: str, key: str) -> Iterator[bytes] | None:
    from botocore.exceptions import ClientError
    s3, _ = _storage()
    try:
        body = s3.get_object(Bucket=bucket, Key=key)["Body"]
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code", "") in ("NoSuchKey", "404", "NotFound"):
            return None
        raise
    return body.iter_chunks(CHUNK)


def _list_reports(case_id: str, limit: int) -> list[dict]:
    col = _database()[config.REPORTS_COLLECTION]
    return list(col.find({"case_id": case_id}, {"pdf": 0}).sort("generated_at", -1).limit(limit))


async def save_report(meta: dict, pdf: bytes) -> dict:
    if len(pdf) > MAX_PDF_BYTES:
        raise ValueError(f"The report is {len(pdf):,} bytes, over the {MAX_PDF_BYTES:,} byte limit.")
    return await _run(_save_report, meta, pdf)


async def get_report(filename: str) -> dict | None:
    return await _run(_get_report, filename)


async def open_report(row: dict) -> Iterator[bytes] | None:
    """The report file as chunks, or None when it is missing from storage."""
    if "pdf" in row:  # made before the move to object storage
        data = bytes(row["pdf"])
        return iter([data])
    return await _run(_open_object, row.get("bucket") or config.GARAGE_BUCKET, row["object_key"])


async def list_reports(case_id: str, limit: int = 50) -> list[dict]:
    return await _run(_list_reports, case_id, limit)
