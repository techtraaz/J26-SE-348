"""MongoDB trace reader — the heart of Component 04.

Runs as a long-lived asyncio background task that:
  1. Connects to MongoDB and polls the ``c03_callback_traces`` collection.
  2. Deserialises each new document into a typed Pydantic model.
  3. Enriches the event with a ``received_at`` timestamp and its run identity.
  4. Broadcasts the enriched trace to connected SSE clients in real time
     (granular ``step`` events are rendered to readable rows first).
  5. Persists the event into the local SQLite Middle DB (steps in one
     transaction per poll, so the live stream never waits on SQLite).

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
from app.services import review_agent
from app.services import sse_manager
from app.services import step_renderer

logger = logging.getLogger("c04.trace_reader")

# ── In-memory state ───────────────────────────────────────────────────
# (case_id, run) -> highest seq seen (so we only process new events).
# Keyed per run: every audit run and Copilot turn numbers its events from 1.
_last_seen: dict[tuple[str, str], int] = {}

# ── Per-case step counter for SSE ─────────────────────────────────────
_step_counters: dict[str, int] = {}

# ── Latest audit_run id per case, so steps need no DB lookup ──────────
_run_ids: dict[str, int] = {}

# ── Step rows waiting to be written in one transaction (see flush) ────
_pending_rows: list[dict] = []


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_step(case_id: str) -> int:
    _step_counters[case_id] = _step_counters.get(case_id, 0) + 1
    return _step_counters[case_id]


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
        "copilot_start": "run_start",
        "copilot_nlu": "agent_done",
        "copilot_end": "run_end",
        "step": "step",
    }.get(evt.event_type, "trace")


async def _publish(evt: CallbackEvent, payload: dict) -> None:
    """Broadcast one payload, stamped with its run, to the case's stream and
    to the stream that started the run (e.g. the chat that ran an audit)."""
    payload.setdefault("case_id", evt.case_id)
    payload.setdefault("source_timestamp", evt.ts)
    payload.setdefault("received_at", _now_iso())
    payload.update(
        run_key=evt.run_key,
        run_kind=evt.run_kind or ("copilot" if evt.event_type.startswith("copilot") else "audit"),
        version=evt.version,
        seq=evt.seq,
    )
    await sse_manager.broadcast(evt.case_id, payload)
    if evt.stream_id and evt.stream_id != evt.case_id:
        await sse_manager.broadcast(evt.stream_id, payload)


def _stage(agent: str | None) -> dict:
    return {"stage": agent, "label": step_renderer.stage_label(agent), "agent_name": agent}


async def _latest_run_id(case_id: str) -> int:
    run = await db.get_latest_run(case_id)
    return run["id"] if run else 0


# ── Event handlers ────────────────────────────────────────────────────

async def _handle_pipeline_start(evt: CallbackEvent) -> None:
    """Broadcast the start, then create an audit_run row for later events."""
    _step_counters[evt.case_id] = 0
    detail = f"Pipeline started with {evt.doc_count or 0} document(s)."
    await _publish(evt, {
        "event_type": "pipeline_start",
        "step_index": 0,
        "doc_count": evt.doc_count or 0,
        "detail": detail,
    })
    run_id = await db.insert_audit_run(
        case_id=evt.case_id,
        doc_count=evt.doc_count or 0,
        started_at=evt.ts,
    )
    _run_ids[evt.case_id] = run_id
    await db.insert_trace(
        run_id=run_id,
        case_id=evt.case_id,
        event_type="pipeline_start",
        agent_name=None,
        decision_type=None,
        detail=detail,
        findings_count=None,
        step_index=0,
        duration_ms=None,
        source_timestamp=evt.ts,
        received_at=_now_iso(),
        raw_payload=evt.model_dump(),
    )
    logger.info("▶ Pipeline started  case=%s  docs=%s", evt.case_id, evt.doc_count)


async def _handle_chain_start(evt: CallbackEvent) -> None:
    """An agent is beginning its work — broadcast 'thinking' state."""
    if not evt.agent:
        return
    step = _next_step(evt.case_id)
    await _publish(evt, {"event_type": "agent_thinking", "step_index": step, **_stage(evt.agent)})
    logger.info("  ├─ Agent thinking  agent=%s  step=%s", evt.agent, step)


async def _handle_chain_end(evt: CallbackEvent) -> None:
    """An agent finished — broadcast, then persist the trace."""
    if not evt.agent:
        return
    step = _next_step(evt.case_id)

    # Extract summary data from the callback
    findings_count = evt.data.get("findings_count") or evt.data.get("final_findings_count")
    details = evt.data.get("trace_details") or []
    detail = ((details[0] if details else None) or evt.data.get("trace_preview")
              or f"Agent {evt.agent} completed.")

    await _publish(evt, {
        "event_type": "agent_done",
        **_stage(evt.agent),
        "detail": detail,
        "details": details,
        "findings_count": findings_count,
        "duration_ms": evt.duration_ms,
        "step_index": step,
    })
    await flush_pending()  # the agent's steps land in the DB before its summary
    await db.insert_trace(
        run_id=_run_ids.get(evt.case_id) or await _latest_run_id(evt.case_id),
        case_id=evt.case_id,
        event_type="chain_end",
        agent_name=evt.agent,
        decision_type="agent_complete",
        detail=detail,
        findings_count=findings_count,
        step_index=step,
        duration_ms=evt.duration_ms,
        source_timestamp=evt.ts,
        received_at=_now_iso(),
        raw_payload=evt.model_dump(),
    )
    logger.info("  ├─ Agent done  agent=%s  duration=%sms  step=%s",
                evt.agent, evt.duration_ms, step)


async def _handle_chain_error(evt: CallbackEvent) -> None:
    """An agent errored — broadcast, then persist."""
    step = _next_step(evt.case_id)
    await _publish(evt, {
        "event_type": "agent_error",
        **_stage(evt.agent),
        "error": evt.error,
        "detail": evt.error or "Unknown error",
        "duration_ms": evt.duration_ms,
        "step_index": step,
    })
    await flush_pending()
    await db.insert_trace(
        run_id=_run_ids.get(evt.case_id) or await _latest_run_id(evt.case_id),
        case_id=evt.case_id,
        event_type="chain_error",
        agent_name=evt.agent,
        decision_type="error",
        detail=evt.error or "Unknown error",
        findings_count=None,
        step_index=step,
        duration_ms=evt.duration_ms,
        source_timestamp=evt.ts,
        received_at=_now_iso(),
        raw_payload=evt.model_dump(),
    )
    logger.warning("  ├─ Agent error  agent=%s  error=%s", evt.agent, evt.error)


async def _handle_pipeline_end(evt: CallbackEvent) -> None:
    """Broadcast the end, finalise the audit run row, clean up in-memory state."""
    step = (_step_counters.pop(evt.case_id, 0)) + 1
    detail = f"Pipeline completed with {evt.total_findings or 0} finding(s)."
    await _publish(evt, {
        "event_type": "pipeline_end",
        "total_findings": evt.total_findings,
        "status": evt.status,
        "step_index": step,
        "detail": detail,
    })
    await flush_pending()  # the run's steps are in the DB before it is closed

    await db.complete_audit_run(
        case_id=evt.case_id,
        total_findings=evt.total_findings or 0,
    )
    await db.insert_trace(
        run_id=_run_ids.get(evt.case_id) or await _latest_run_id(evt.case_id),
        case_id=evt.case_id,
        event_type="pipeline_end",
        agent_name=None,
        decision_type=None,
        detail=f"Pipeline completed with {evt.total_findings or 0} finding(s). Status: {evt.status}.",
        findings_count=evt.total_findings,
        step_index=step,
        duration_ms=None,
        source_timestamp=evt.ts,
        received_at=_now_iso(),
        raw_payload=evt.model_dump(),
    )
    logger.info("■ Pipeline ended  case=%s  findings=%s  status=%s",
                evt.case_id, evt.total_findings, evt.status)

    # Fire-and-forget: the Review Agent writes the run's verdict and summary
    asyncio.create_task(review_agent.review_run(
        evt.case_id, evt.run_key, evt.total_findings or 0, evt.status, evt.stream_id))


# ── Granular step handler ──────────────────────────────────────────────

async def _handle_step(evt: CallbackEvent) -> None:
    """One granular step: broadcast at once, queue the DB row for the batch."""
    step = _next_step(evt.case_id)
    row = step_renderer.render_step(evt.kind or "step", evt.status or "info", evt.facts)
    payload = {"event_type": "step", **_stage(evt.agent), **row,
               "duration_ms": evt.duration_ms, "step_index": step}
    await _publish(evt, payload)
    _pending_rows.append({
        "run_id": _run_ids.get(evt.case_id, 0),
        "case_id": evt.case_id,
        "event_type": "step",
        "agent_name": evt.agent,
        "decision_type": evt.kind,
        "detail": f"{row['verb']} {row['target']}: {row['detail']}".strip(": "),
        "findings_count": None,
        "step_index": step,
        "duration_ms": evt.duration_ms,
        "source_timestamp": evt.ts,
        "received_at": payload["received_at"],
        "raw_payload": {**evt.model_dump(), "rendered": row},
    })


async def flush_pending() -> None:
    """Write queued step rows in one transaction. Non-fatal on failure.

    Steps outside an audit run (Copilot turns) have no audit_runs row to point
    to; they are streamed live only, so one of them never fails the batch."""
    if not _pending_rows:
        return
    rows = [r for r in _pending_rows if r["run_id"]]
    _pending_rows.clear()
    if not rows:
        return
    try:
        await db.insert_traces(rows)
    except Exception:
        logger.warning("Could not persist %d step row(s) (non-fatal)", len(rows), exc_info=True)


# ── Copilot event handler ──────────────────────────────────────────────

async def _handle_copilot(evt: CallbackEvent) -> None:
    """A Copilot turn: start -> understanding the request -> preparing the
    answer -> end. Broadcast to SSE first so the live panel updates
    immediately, then persist (non-fatal if it fails)."""
    step = _next_step(evt.case_id)
    detail = evt.detail or evt.data.get("detail", "")

    if evt.event_type == "copilot_start":
        await _publish(evt, {"event_type": "run_start", "detail": detail, "step_index": step})
        await _publish(evt, {"event_type": "agent_thinking", "step_index": step,
                             **_stage("copilot_nlu")})
    elif evt.event_type == "copilot_nlu":
        row = step_renderer.render_intent(evt.intent, evt.nlu_method)
        await _publish(evt, {"event_type": "step", **_stage("copilot_nlu"), **row,
                             "step_index": step})
        await _publish(evt, {"event_type": "agent_done", **_stage("copilot_nlu"),
                             "detail": detail, "step_index": step})
        await _publish(evt, {"event_type": "agent_thinking", "step_index": step,
                             **_stage("copilot")})
    else:  # copilot_end
        await _publish(evt, {"event_type": "agent_done", **_stage("copilot"),
                             "detail": detail, "duration_ms": evt.duration_ms,
                             "step_index": step})
        await _publish(evt, {"event_type": "run_end", "detail": detail, "intent": evt.intent,
                             "status": evt.status, "duration_ms": evt.duration_ms,
                             "step_index": step})

    # Then persist to SQLite (non-fatal if it fails)
    try:
        await flush_pending()
        await db.insert_trace(
            run_id=_run_ids.get(evt.case_id) or await _latest_run_id(evt.case_id),
            case_id=evt.case_id,
            event_type=evt.event_type,
            agent_name=evt.agent or "copilot",
            decision_type="copilot",
            detail=detail,
            findings_count=None,
            step_index=step,
            duration_ms=evt.duration_ms,
            source_timestamp=evt.ts,
            received_at=_now_iso(),
            raw_payload=evt.model_dump(),
        )
    except Exception:
        logger.debug("Copilot trace DB write failed (non-fatal)", exc_info=True)

    logger.info("  ├─ Copilot %s  case=%s  detail=%s",
                evt.event_type, evt.case_id, (detail or "")[:60])


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
        case "step":
            await _handle_step(evt)
        case "copilot_start" | "copilot_nlu" | "copilot_end":
            await _handle_copilot(evt)
        case _:
            logger.debug("Ignoring event type: %s", evt.event_type)


def _is_new(doc: dict) -> bool:
    """Per-run seq dedup (handles reprocessing edge cases)."""
    key = (doc.get("case_id", ""), doc.get("trace_id") or f"v{doc.get('version', 0)}")
    seq = doc.get("seq", 0)
    if seq <= _last_seen.get(key, 0):
        return False
    _last_seen[key] = seq
    return True


async def process_batch(docs: list[dict]) -> int:
    """Dispatch raw MongoDB documents in order, then persist the queued step
    rows in one transaction. Returns how many documents were new."""
    new_count = 0
    for doc in docs:
        if not _is_new(doc):
            continue
        new_count += 1
        await _dispatch(doc)
    await flush_pending()
    return new_count


# ── Main reader loop ──────────────────────────────────────────────────

# Track the last MongoDB ObjectId we've seen — so we only query newer docs.
from bson import ObjectId as _ObjectId

_last_oid: _ObjectId | None = None


async def run_reader() -> None:
    """Poll MongoDB for new callback traces and process them.

    This function is designed to be launched via ``asyncio.create_task``
    during FastAPI's lifespan.  It retries on connection failures with
    exponential backoff so a MongoDB outage never kills the server.
    """
    global _last_oid
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
                    # Only query documents newer than the last one we processed
                    query: dict = {}
                    if _last_oid is not None:
                        query["_id"] = {"$gt": _last_oid}

                    docs = list(col.find(
                        query,
                        sort=[("_id", 1)],
                        limit=200,
                    ))
                    if docs and docs[-1].get("_id") is not None:
                        _last_oid = docs[-1]["_id"]  # update the global cursor
                    new_count = await process_batch(docs)

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
