"""Redis Pub/Sub subscriber — the heart of Component 04.

Runs as a long-lived asyncio background task that:
  1. Connects to Redis and subscribes to the ``nomos:trace_events`` channel.
  2. Deserialises each incoming message into a typed Pydantic model.
  3. Enriches the event with a ``received_at`` timestamp.
  4. Persists the event into the local SQLite Middle DB.
  5. Broadcasts the enriched trace to connected SSE clients in real time.

Design principles:
  - **Non-blocking**: runs inside ``asyncio.create_task`` so the FastAPI
    event loop is never stalled.
  - **Resilient**: if Redis is temporarily unavailable the listener sleeps
    and retries — it never crashes the host process.
  - **Independent**: C03 fires and forgets; C04 decides what to keep.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app import config
from app.schemas.trace_events import (
    AgentEndEvent,
    PipelineEndEvent,
    PipelineStartEvent,
    parse_trace_event,
)
from app.services import database as db
from app.services import insight_generator
from app.services import sse_manager

logger = logging.getLogger("c04.subscriber")

# ── In-memory lookup: case_id -> active run_id ────────────────────────
# Needed so agent_end / pipeline_end events can reference the correct
# audit_run row that was created by the matching pipeline_start event.
_active_runs: dict[str, int] = {}

# ── Per-case step counter ─────────────────────────────────────────────
_step_counters: dict[str, int] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Event handlers ────────────────────────────────────────────────────

async def _handle_pipeline_start(evt: PipelineStartEvent) -> None:
    """Create an audit_run row and record the run_id for later events."""
    run_id = await db.insert_audit_run(
        case_id=evt.case_id,
        doc_count=evt.doc_count,
        started_at=evt.ts,
    )
    _active_runs[evt.case_id] = run_id
    _step_counters[evt.case_id] = 0

    received = _now_iso()
    await db.insert_trace(
        run_id=run_id,
        case_id=evt.case_id,
        event_type="pipeline_start",
        agent_name=None,
        decision_type=None,
        detail=f"Pipeline started with {evt.doc_count} document(s).",
        findings_count=None,
        step_index=0,
        source_timestamp=evt.ts,
        received_at=received,
        raw_payload=evt.model_dump(),
    )
    await sse_manager.broadcast(evt.case_id, {
        "event_type": "pipeline_start",
        "case_id": evt.case_id,
        "step_index": 0,
        "detail": f"Pipeline started with {evt.doc_count} document(s).",
        "source_timestamp": evt.ts,
        "received_at": received,
    })
    logger.info("▶ Pipeline started  case=%s  docs=%s  run_id=%s", evt.case_id, evt.doc_count, run_id)


async def _handle_agent_end(evt: AgentEndEvent) -> None:
    """Persist an individual agent trace step."""
    run_id = _active_runs.get(evt.case_id)
    if run_id is None:
        logger.warning("agent_end for case=%s but no active run — skipping", evt.case_id)
        return

    _step_counters[evt.case_id] = _step_counters.get(evt.case_id, 0) + 1
    step = _step_counters[evt.case_id]

    received = _now_iso()
    await db.insert_trace(
        run_id=run_id,
        case_id=evt.case_id,
        event_type="agent_end",
        agent_name=evt.agent,
        decision_type=evt.trace.get("decision_type"),
        detail=evt.trace.get("detail"),
        findings_count=evt.findings_count,
        step_index=step,
        source_timestamp=evt.ts,
        received_at=received,
        raw_payload=evt.model_dump(),
    )
    await sse_manager.broadcast(evt.case_id, {
        "event_type": "agent_end",
        "case_id": evt.case_id,
        "agent_name": evt.agent,
        "decision_type": evt.trace.get("decision_type"),
        "detail": evt.trace.get("detail"),
        "findings_count": evt.findings_count,
        "step_index": step,
        "source_timestamp": evt.ts,
        "received_at": received,
    })
    logger.info("  ├─ Agent done  agent=%s  findings=%s  step=%s", evt.agent, evt.findings_count, step)


async def _handle_pipeline_end(evt: PipelineEndEvent) -> None:
    """Finalise the audit run row and clean up in-memory state."""
    run_id = _active_runs.pop(evt.case_id, None)
    step = (_step_counters.pop(evt.case_id, 0)) + 1

    if run_id is None:
        logger.warning("pipeline_end for case=%s but no active run — skipping", evt.case_id)
        return

    await db.complete_audit_run(
        case_id=evt.case_id,
        total_findings=evt.total_findings,
    )
    received = _now_iso()
    await db.insert_trace(
        run_id=run_id,
        case_id=evt.case_id,
        event_type="pipeline_end",
        agent_name=None,
        decision_type=None,
        detail=f"Pipeline completed with {evt.total_findings} total finding(s).",
        findings_count=evt.total_findings,
        step_index=step,
        source_timestamp=evt.ts,
        received_at=received,
        raw_payload=evt.model_dump(),
    )
    await sse_manager.broadcast(evt.case_id, {
        "event_type": "pipeline_end",
        "case_id": evt.case_id,
        "total_findings": evt.total_findings,
        "step_index": step,
        "detail": f"Pipeline completed with {evt.total_findings} total finding(s).",
        "source_timestamp": evt.ts,
        "received_at": received,
    })
    logger.info("■ Pipeline ended  case=%s  total_findings=%s", evt.case_id, evt.total_findings)

    # Fire-and-forget: let the Insight Generator decide if an AI summary is needed
    asyncio.create_task(insight_generator.maybe_generate_insight(evt.case_id, evt.total_findings))


# ── Dispatcher ─────────────────────────────────────────────────────────

async def _dispatch(event_data: dict) -> None:
    """Parse, enrich, and persist a single raw event."""
    evt = parse_trace_event(event_data)

    match evt:
        case PipelineStartEvent():
            await _handle_pipeline_start(evt)
        case AgentEndEvent():
            await _handle_agent_end(evt)
        case PipelineEndEvent():
            await _handle_pipeline_end(evt)


# ── Main listener loop ─────────────────────────────────────────────────

async def run_listener() -> None:
    """Subscribe to Redis and process trace events forever.

    This function is designed to be launched via ``asyncio.create_task``
    during FastAPI's lifespan.  It retries on connection failures with
    exponential backoff so a Redis outage never kills the server.
    """
    backoff = 1  # seconds, doubles on each failure up to a cap

    while True:
        try:
            logger.info("Connecting to Redis at %s …", config.REDIS_URL)
            client = aioredis.from_url(config.REDIS_URL, decode_responses=True)
            pubsub = client.pubsub()
            await pubsub.subscribe(config.TRACE_CHANNEL)
            logger.info("✓ Subscribed to channel '%s'", config.TRACE_CHANNEL)
            backoff = 1  # reset on success

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                    await _dispatch(data)
                except (json.JSONDecodeError, ValueError) as exc:
                    logger.warning("Skipping malformed event: %s", exc)
                except Exception:
                    logger.exception("Unexpected error processing event")

        except asyncio.CancelledError:
            logger.info("Subscriber task cancelled — shutting down cleanly.")
            return
        except Exception:
            logger.exception("Redis connection lost — retrying in %ss", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
