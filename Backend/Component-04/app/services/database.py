"""Async SQLite database for persisting audit runs and individual traces.

This is the 'Middle DB' — Component 04 owns it exclusively.  C03 never
touches this database; C04 writes here after independently capturing and
verifying trace events from the Redis event bus.

Two tables:
  audit_runs — one row per audit pipeline execution (case-level metadata)
  traces     — one row per agent step or pipeline event within a run
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import aiosqlite

from app import config

logger = logging.getLogger("c04.database")

# ── Schema DDL ─────────────────────────────────────────────────────────

_CREATE_AUDIT_RUNS = """
CREATE TABLE IF NOT EXISTS audit_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id       TEXT    NOT NULL,
    doc_count     INTEGER DEFAULT 0,
    started_at    TEXT    NOT NULL,
    ended_at      TEXT,
    total_findings INTEGER,
    status        TEXT    NOT NULL DEFAULT 'running'
);
"""

_CREATE_TRACES = """
CREATE TABLE IF NOT EXISTS traces (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           INTEGER NOT NULL REFERENCES audit_runs(id),
    case_id          TEXT    NOT NULL,
    event_type       TEXT    NOT NULL,
    agent_name       TEXT,
    decision_type    TEXT,
    detail           TEXT,
    findings_count   INTEGER,
    step_index       INTEGER NOT NULL DEFAULT 0,
    source_timestamp TEXT    NOT NULL,
    received_at      TEXT    NOT NULL,
    raw_payload      TEXT    NOT NULL
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_traces_case ON traces(case_id);
"""


# ── Connection helpers ─────────────────────────────────────────────────

async def get_connection() -> aiosqlite.Connection:
    """Open (or reuse) an async SQLite connection with WAL mode."""
    conn = await aiosqlite.connect(config.DATABASE_PATH)
    await conn.execute("PRAGMA journal_mode=WAL;")
    await conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = aiosqlite.Row
    return conn


async def init_db() -> None:
    """Create tables if they do not exist.  Safe to call on every startup."""
    async with await get_connection() as db:
        await db.execute(_CREATE_AUDIT_RUNS)
        await db.execute(_CREATE_TRACES)
        await db.execute(_CREATE_INDEX)
        await db.commit()
    logger.info("Database initialised at %s", config.DATABASE_PATH)


# ── Write operations ──────────────────────────────────────────────────

async def insert_audit_run(
    case_id: str,
    doc_count: int,
    started_at: str,
) -> int:
    """Create a new audit_run row and return its id."""
    async with await get_connection() as db:
        cursor = await db.execute(
            "INSERT INTO audit_runs (case_id, doc_count, started_at) VALUES (?, ?, ?)",
            (case_id, doc_count, started_at),
        )
        await db.commit()
        run_id = cursor.lastrowid
    logger.info("Created audit_run id=%s for case=%s", run_id, case_id)
    return run_id  # type: ignore[return-value]


async def complete_audit_run(
    case_id: str,
    total_findings: int,
) -> None:
    """Mark the most recent 'running' audit_run for this case as completed."""
    ended_at = datetime.now(timezone.utc).isoformat()
    async with await get_connection() as db:
        await db.execute(
            """UPDATE audit_runs
               SET status = 'completed', ended_at = ?, total_findings = ?
               WHERE case_id = ? AND status = 'running'
               ORDER BY id DESC LIMIT 1""",
            (ended_at, total_findings, case_id),
        )
        await db.commit()
    logger.info("Completed audit_run for case=%s  findings=%s", case_id, total_findings)


async def insert_trace(
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
) -> int:
    """Persist a single trace row and return its id."""
    async with await get_connection() as db:
        cursor = await db.execute(
            """INSERT INTO traces
               (run_id, case_id, event_type, agent_name, decision_type,
                detail, findings_count, step_index, source_timestamp,
                received_at, raw_payload)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, case_id, event_type, agent_name, decision_type,
                detail, findings_count, step_index, source_timestamp,
                received_at, json.dumps(raw_payload, default=str),
            ),
        )
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


# ── Read operations (for future API endpoints) ────────────────────────

async def get_runs(limit: int = 50) -> list[dict]:
    """Return the most recent audit runs."""
    async with await get_connection() as db:
        cursor = await db.execute(
            "SELECT * FROM audit_runs ORDER BY id DESC LIMIT ?", (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_traces_for_case(case_id: str) -> list[dict]:
    """Return all traces for a given case, ordered by step index."""
    async with await get_connection() as db:
        cursor = await db.execute(
            "SELECT * FROM traces WHERE case_id = ? ORDER BY step_index ASC",
            (case_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
