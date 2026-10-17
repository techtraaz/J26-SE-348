"""Async MongoDB Atlas connection layer for persistent trace storage.

This module provides a secondary storage backend for Component 04.
SQLite remains as the fast local cache, while MongoDB Atlas serves as
the durable, shared remote database for audit runs and traces.

Collections:
  audit_runs — one document per audit pipeline execution
  traces     — one document per agent step or pipeline event
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

from app import config

logger = logging.getLogger("c04.mongodb")

# ── Lazy client (created on first use) ─────────────────────────────────

_client: AsyncIOMotorClient | None = None
_db = None


def _get_db():
    """Lazy-init the MongoDB client and return the database handle."""
    global _client, _db
    if _db is not None:
        return _db
    _client = AsyncIOMotorClient(config.MONGODB_URI)
    _db = _client[config.MONGODB_DB_NAME]
    logger.info("MongoDB connected to database '%s'", config.MONGODB_DB_NAME)
    return _db


async def ping() -> bool:
    """Test the MongoDB connection. Returns True if reachable."""
    try:
        db = _get_db()
        await db.command("ping")
        return True
    except Exception as exc:
        logger.warning("MongoDB ping failed: %s", exc)
        return False


# ── Write operations ──────────────────────────────────────────────────

async def save_audit_run(
    case_id: str,
    doc_count: int,
    started_at: str,
    run_id: int,
) -> None:
    """Persist an audit run document to MongoDB."""
    try:
        db = _get_db()
        await db.audit_runs.insert_one({
            "local_run_id": run_id,
            "case_id": case_id,
            "doc_count": doc_count,
            "started_at": started_at,
            "status": "running",
            "created_at": datetime.now(timezone.utc),
        })
        logger.info("MongoDB: saved audit_run for case=%s", case_id)
    except Exception:
        logger.warning("MongoDB: failed to save audit_run (non-fatal)", exc_info=True)


async def complete_audit_run(
    case_id: str,
    total_findings: int,
) -> None:
    """Mark the audit run as completed in MongoDB."""
    try:
        db = _get_db()
        await db.audit_runs.update_one(
            {"case_id": case_id, "status": "running"},
            {"$set": {
                "status": "completed",
                "total_findings": total_findings,
                "ended_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=False,
        )
        logger.info("MongoDB: completed audit_run for case=%s", case_id)
    except Exception:
        logger.warning("MongoDB: failed to complete audit_run (non-fatal)", exc_info=True)


async def save_trace(
    *,
    run_id: int,
    case_id: str,
    event_type: str,
    agent_name: str | None,
    decision_type: str | None,
    detail: str | None,
    findings_count: int | None,
    step_index: int,
    source_timestamp: str,
    received_at: str,
    raw_payload: dict,
) -> None:
    """Persist a single trace document to MongoDB."""
    try:
        db = _get_db()
        await db.traces.insert_one({
            "local_run_id": run_id,
            "case_id": case_id,
            "event_type": event_type,
            "agent_name": agent_name,
            "decision_type": decision_type,
            "detail": detail,
            "findings_count": findings_count,
            "step_index": step_index,
            "source_timestamp": source_timestamp,
            "received_at": received_at,
            "raw_payload": raw_payload,
            "stored_at": datetime.now(timezone.utc),
        })
    except Exception:
        logger.warning("MongoDB: failed to save trace (non-fatal)", exc_info=True)


# ── Read operations ───────────────────────────────────────────────────

async def get_runs(limit: int = 50) -> list[dict]:
    """Return the most recent audit runs from MongoDB."""
    try:
        db = _get_db()
        cursor = db.audit_runs.find(
            {}, {"_id": 0}
        ).sort("created_at", -1).limit(limit)
        return await cursor.to_list(length=limit)
    except Exception:
        logger.warning("MongoDB: failed to fetch runs (non-fatal)", exc_info=True)
        return []


async def get_traces_for_case(case_id: str) -> list[dict]:
    """Return all traces for a given case from MongoDB, ordered by step index."""
    try:
        db = _get_db()
        cursor = db.traces.find(
            {"case_id": case_id}, {"_id": 0}
        ).sort("step_index", 1)
        return await cursor.to_list(length=1000)
    except Exception:
        logger.warning("MongoDB: failed to fetch traces (non-fatal)", exc_info=True)
        return []
