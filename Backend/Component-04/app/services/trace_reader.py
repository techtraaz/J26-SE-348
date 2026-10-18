"""MongoDB trace reader — the heart of Component 04.

Runs as a long-lived asyncio background task that:
  1. Connects to MongoDB and polls the ``c03_callback_traces`` collection.
  2. Deserialises each new document into a typed Pydantic model.
  3. Enriches the event with a ``received_at`` timestamp.
  4. Persists the event into the local SQLite Middle DB.
  5. Broadcasts the enriched trace to connected SSE clients in real time.

Design principles:
  - **Non-blocking**: runs inside ``asyncio.create_task`` so the FastAPI
    event loop is never stalled.
  - **Resilient**: if MongoDB is temporarily unavailable the reader sleeps
    and retries — it never crashes the host process.
  - **Independent**: C03 writes fire-and-forget; C04 decides what to keep.
  - **Polling**: queries every TRACE_POLL_INTERVAL_MS ms for new events
    (simpler than change streams, no replica set requirement for dev).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from pymongo import MongoClient

from app import config
from app.schemas.callback_events import CallbackEvent, parse_callback_event
from app.services import database as db
from app.services import insight_generator
from app.services import sse_manager

logger = logging.getLogger("c04.trace_reader")

# ── In-memory state ───────────────────────────────────────────────────
# case_id -> highest seq seen (so we only process new events)
_last_seen: dict[str, int] = {}

# ── Per-case step counter for SSE ─────────────────────────────────────
_step_counters: dict[str, int] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sse_event_type(evt: CallbackEvent) -> str:
    """Map callback event types to SSE event names for the frontend."""
    return {
        "pipeline_start": "pipeline_start",
        "chain_start": "agent_thinking",
        "chain_end": "agent_done",
        "chain_error": "agent_error",
        "llm_start": "llm_thinking",
        "llm_end": "llm_done",
        "llm_error": "llm_error",
        "pipeline_end": "pipeline_end",
    }.get(evt.event_type, "trace")


# ── Event handlers ────────────────────────────────────────────────────

async def _handle_pipeline_start(evt: CallbackEvent) -> None:
    """Create an audit_run row and record the run_id for later events."""
    run_id = await db.insert_audit_run(
        case_id=evt.case_id,
        doc_count=evt.doc_count or 0,
        started_at=evt.ts,
    )
    _step_counters[evt.case_id] = 0
    received = _now_iso()

    await db.insert_trace(
        run_id=run_id,
        case_id=evt.case_id,
        event_type="pipeline_start",
        agent_name=None,
        decision_type=None,
        detail=f"Pipeline started with {evt.doc_count or 0} document(s).",
        findings_count=None,
        step_index=0,
        duration_ms=None,
        source_timestamp=evt.ts,
        received_at=received,
        raw_payload=evt.model_dump(),
    )
    await sse_manager.broadcast(evt.case_id, {
        "event_type": "pipeline_start",
        "case_id": evt.case_id,
        "step_index": 0,
        "detail": f"Pipeline started with {evt.doc_count or 0} document(s).",
        "source_timestamp": evt.ts,
        "received_at": received,
    })
    logger.info("▶ Pipeline started  case=%s  docs=%s", evt.case_id, evt.doc_count)


async def _handle_chain_start(evt: CallbackEvent) -> None:
    """An agent is beginning its work — broadcast 'thinking' state."""
    _step_counters[evt.case_id] = _step_counters.get(evt.case_id, 0) + 1
    step = _step_counters[evt.case_id]
    received = _now_iso()

    await sse_manager.broadcast(evt.case_id, {
        "event_type": "agent_thinking",
        "case_id": evt.case_id,
        "agent_name": evt.agent,
        "step_index": step,
        "source_timestamp": evt.ts,
        "received_at": received,
    })
    logger.info("  ├─ Agent thinking  agent=%s  step=%s", evt.agent, step)


async def _handle_chain_end(evt: CallbackEvent) -> None:
    """An agent finished — persist trace and broadcast."""
    run = await db.get_latest_run(evt.case_id)
    run_id = run["id"] if run else 0

    _step_counters[evt.case_id] = _step_counters.get(evt.case_id, 0) + 1
    step = _step_counters[evt.case_id]
    received = _now_iso()

    # Extract summary data from the callback
    findings_count = evt.data.get("findings_count") or evt.data.get("final_findings_count")
    detail = evt.data.get("trace_preview") or f"Agent {evt.agent or 'unknown'} completed."

    await db.insert_trace(
        run_id=run_id,
        case_id=evt.case_id,
        event_type="chain_end",
        agent_name=evt.agent,
        decision_type="agent_complete",
        detail=detail,
        findings_count=findings_count,
        step_index=step,
        duration_ms=evt.duration_ms,
        source_timestamp=evt.ts,
        received_at=received,
        raw_payload=evt.model_dump(),
    )
    await sse_manager.broadcast(evt.case_id, {
        "event_type": "agent_done",
        "case_id": evt.case_id,
        "agent_name": evt.agent,
        "detail": detail,
        "findings_count": findings_count,
        "duration_ms": evt.duration_ms,
        "step_index": step,
        "source_timestamp": evt.ts,
        "received_at": received,
    })
    logger.info("  ├─ Agent done  agent=%s  duration=%sms  step=%s",
                evt.agent, evt.duration_ms, step)


async def _handle_chain_error(evt: CallbackEvent) -> None:
    """An agent errored — persist and broadcast."""
    run = await db.get_latest_run(evt.case_id)
    run_id = run["id"] if run else 0

    _step_counters[evt.case_id] = _step_counters.get(evt.case_id, 0) + 1
    step = _step_counters[evt.case_id]
    received = _now_iso()

    await db.insert_trace(
        run_id=run_id,
        case_id=evt.case_id,
        event_type="chain_error",
        agent_name=evt.agent,
        decision_type="error",
        detail=evt.error or "Unknown error",
        findings_count=None,
        step_index=step,
        duration_ms=evt.duration_ms,
        source_timestamp=evt.ts,
        received_at=received,
        raw_payload=evt.model_dump(),
    )
    await sse_manager.broadcast(evt.case_id, {
        "event_type": "agent_error",
        "case_id": evt.case_id,
        "agent_name": evt.agent,
        "error": evt.error,
        "duration_ms": evt.duration_ms,
        "step_index": step,
        "source_timestamp": evt.ts,
        "received_at": received,
    })
    logger.warning("  ├─ Agent error  agent=%s  error=%s", evt.agent, evt.error)


async def _handle_pipeline_end(evt: CallbackEvent) -> None:
    """Finalise the audit run row and clean up in-memory state."""
    step = (_step_counters.pop(evt.case_id, 0)) + 1

    await db.complete_audit_run(
        case_id=evt.case_id,
        total_findings=evt.total_findings or 0,
    )
    received = _now_iso()
    run = await db.get_latest_run(evt.case_id)
    run_id = run["id"] if run else 0

    await db.insert_trace(
        run_id=run_id,
        case_id=evt.case_id,
        event_type="pipeline_end",
        agent_name=None,
        decision_type=None,
        detail=f"Pipeline completed with {evt.total_findings or 0} finding(s). Status: {evt.status}.",
        findings_count=evt.total_findings,
        step_index=step,
        duration_ms=None,
        source_timestamp=evt.ts,
        received_at=received,
        raw_payload=evt.model_dump(),
    )
    await sse_manager.broadcast(evt.case_id, {
        "event_type": "pipeline_end",
        "case_id": evt.case_id,
        "total_findings": evt.total_findings,
        "status": evt.status,
        "step_index": step,
        "detail": f"Pipeline completed with {evt.total_findings or 0} finding(s).",
        "source_timestamp": evt.ts,
        "received_at": received,
    })
    logger.info("■ Pipeline ended  case=%s  findings=%s  status=%s",
                evt.case_id, evt.total_findings, evt.status)

    # Fire-and-forget: let the Insight Generator decide if an AI summary is needed
    asyncio.create_task(
        insight_generator.maybe_generate_insight(evt.case_id, evt.total_findings or 0))


# ── Dispatcher ─────────────────────────────────────────────────────────

async def _dispatch(raw: dict) -> None:
    """Parse, enrich, and persist a single raw callback event."""
    try:
        evt = parse_callback_event(raw)
    except Exception:
        logger.warning("Skipping malformed callback event: %s", raw.get("event_type"))
        return

    match evt.event_type:
        case "pipeline_start":
            await _handle_pipeline_start(evt)
        case "chain_start":
            await _handle_chain_start(evt)
        case "chain_end":
            await _handle_chain_end(evt)
        case "chain_error":
            await _handle_chain_error(evt)
        case "pipeline_end":
            await _handle_pipeline_end(evt)
        case _:
            logger.debug("Ignoring event type: %s", evt.event_type)


# ── Main reader loop ──────────────────────────────────────────────────

async def run_reader() -> None:
    """Poll MongoDB for new callback traces and process them.

    This function is designed to be launched via ``asyncio.create_task``
    during FastAPI's lifespan.  It retries on connection failures with
    exponential backoff so a MongoDB outage never kills the server.
    """
    backoff = 1  # seconds, doubles on each failure up to a cap

    while True:
        try:
            if not config.MONGODB_URI:
                logger.warning("MONGODB_URI not configured — trace reader disabled.")
                await asyncio.sleep(30)
                continue

            logger.info("Connecting to MongoDB at %s …", config.MONGODB_URI[:40])
            client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000,
                                 appname="nomos-c04-reader")
            db_handle = client[config.MONGODB_DB_NAME]
            col = db_handle[config.C03_TRACES_COLLECTION]
            logger.info("✓ Connected — polling '%s' every %dms",
                        config.C03_TRACES_COLLECTION, config.TRACE_POLL_INTERVAL_MS)
            backoff = 1  # reset on success

            while True:
                try:
                    # Build query: find events newer than what we've seen
                    query: dict = {}
                    if _last_seen:
                        # Find any event where (case_id, seq) is beyond last seen
                        # Simple approach: query all recent events sorted by _id
                        pass

                    # Fetch new events sorted by insertion order
                    cursor = col.find(
                        {},  # no filter — scan for any unseen events
                        sort=[("_id", 1)],
                        limit=200,
                    )
                    new_count = 0
                    for doc in cursor:
                        case_id = doc.get("case_id", "")
                        seq = doc.get("seq", 0)
                        last = _last_seen.get(case_id, 0)
                        if seq <= last:
                            continue
                        _last_seen[case_id] = seq
                        new_count += 1
                        await _dispatch(doc)

                    if new_count:
                        logger.debug("Processed %d new trace events", new_count)

                except Exception:
                    logger.warning("MongoDB poll query failed — will retry", exc_info=True)

                await asyncio.sleep(config.TRACE_POLL_INTERVAL_MS / 1000)

        except asyncio.CancelledError:
            logger.info("Trace reader task cancelled — shutting down cleanly.")
            return
        except Exception:
            logger.exception("MongoDB connection lost — retrying in %ss", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
