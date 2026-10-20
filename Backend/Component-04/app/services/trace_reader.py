"""MongoDB trace reader — the heart of Component 04.

Runs as a long-lived asyncio background task that:
  1. Connects to MongoDB and polls the ``c03_callback_traces`` collection.
  2. Deserialises each new document into a typed Pydantic model.
  3. Enriches the event with a ``received_at`` timestamp and its run identity.
  4. Broadcasts the enriched trace to connected SSE clients in real time
     (granular ``step`` events are rendered to readable rows first).
  5. Persists the event into the local SQLite Middle DB (steps in one
     transaction per poll, so the live stream never waits on SQLite).

Traces are kept permanently, so the reader never re-reads them all: it saves
how far it has read (``c04_reader_state``) and continues from there after a
restart. Older history is shown on demand: when the panel opens a stream that
this process has not seen yet, ``load_history`` replays that stream's stored
events in a side-effect-free mode (render only — no database writes, no new
Review Agent calls; saved reviews are added from ``c04_reviews``).

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
import contextvars
import logging
from datetime import datetime, timezone

from pymongo import MongoClient

from app import config
from app.schemas.callback_events import CallbackEvent, parse_callback_event
from app.services import database as db
from app.services import (
    report_store,
    review_agent,
    review_store,
    sse_manager,
    step_renderer,
)

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

# ── History replay (load_history): payloads are collected, nothing is written ──
_replay: contextvars.ContextVar[list | None] = contextvars.ContextVar("trace_replay", default=None)
_replay_steps: contextvars.ContextVar[dict | None] = contextvars.ContextVar("trace_replay_steps",
                                                                            default=None)


def _replaying() -> bool:
    return _replay.get() is not None


def _counters() -> dict[str, int]:
    """Step counters: the live ones, or the replay's own (a replay never touches live state)."""
    own = _replay_steps.get()
    return _step_counters if own is None else own


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_step(case_id: str) -> int:
    counters = _counters()
    counters[case_id] = counters.get(case_id, 0) + 1
    return counters[case_id]


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
    sink = _replay.get()
    if sink is not None:  # history replay: collect, do not broadcast
        sink.append(payload)
        return
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
    _counters()[evt.case_id] = 0
    detail = f"Pipeline started with {evt.doc_count or 0} document(s)."
    await _publish(evt, {
        "event_type": "pipeline_start",
        "step_index": 0,
        "doc_count": evt.doc_count or 0,
        "detail": detail,
    })
    if _replaying():
        return
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
    if _replaying():
        return
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
    if _replaying():
        return
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
    step = (_counters().pop(evt.case_id, 0)) + 1
    detail = f"Pipeline completed with {evt.total_findings or 0} finding(s)."
    await _publish(evt, {
        "event_type": "pipeline_end",
        "total_findings": evt.total_findings,
        "status": evt.status,
        "step_index": step,
        "detail": detail,
    })
    if _replaying():
        return
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
    if _replaying():
        return
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
        if not _replaying():
            # Fire-and-forget: the Review Agent wraps up the chat turn
            asyncio.create_task(review_agent.review_turn(evt.case_id, evt.run_key, evt.status))

    if _replaying():
        return
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


# ── History (older events, shown on demand) ───────────────────────────

HISTORY_EVENTS = 800        # stored events replayed per stream
_loaded: set[str] = set()   # streams whose history this process has loaded
_reader_started = asyncio.Event()  # set once run_reader knows where it starts
_reader_running = False


def _history_query(stream_id: str) -> dict:
    query: dict = {"$or": [{"case_id": stream_id}, {"stream_id": stream_id}]}
    if _start_oid is not None:  # newer events reach the panel live
        query["_id"] = {"$lte": _start_oid}
    return query


def _find_history(stream_id: str) -> list[dict]:
    col = report_store.database()[config.C03_TRACES_COLLECTION]
    docs = list(col.find(_history_query(stream_id), sort=[("_id", -1)], limit=HISTORY_EVENTS))
    docs.reverse()
    return docs


async def render_history(docs: list[dict]) -> list[dict]:
    """The SSE payloads those stored events produce, with no side effects."""
    payloads: list[dict] = []
    t1 = _replay.set(payloads)
    t2 = _replay_steps.set({})
    try:
        for doc in docs:
            await _dispatch(doc)
    finally:
        _replay.reset(t1)
        _replay_steps.reset(t2)
    return payloads


async def load_history(stream_id: str) -> None:
    """Before a stream's first subscriber in this process: put its older,
    stored events (and their saved reviews) in front of its live history."""
    if stream_id in _loaded:
        return
    if _reader_running and not _reader_started.is_set():
        # the split between "history" and "live" is where the reader starts: wait for it
        try:
            await asyncio.wait_for(_reader_started.wait(), timeout=10)
        except TimeoutError:
            logger.info("History for %s not loaded yet: the trace reader has not started", stream_id)
            return
    _loaded.add(stream_id)
    try:
        docs = await report_store.run(_find_history, stream_id)
        payloads = await render_history(docs)
        keys = {p.get("run_key") for p in payloads}
        reviews = [r for r in await review_store.reviews_for_stream(stream_id) if r.get("run_key") in keys]
    except report_store.StoreUnavailable as exc:
        _loaded.discard(stream_id)  # try again on the next connection
        logger.warning("History for %s not loaded: %s", stream_id, exc)
        return
    sse_manager.seed(stream_id, payloads + reviews)
    logger.info("History loaded  stream=%s  events=%d  reviews=%d", stream_id, len(docs), len(reviews))


def forget_history(stream_id: str) -> None:
    """After a chat is deleted: drop what this process holds for it."""
    _loaded.discard(stream_id)
    sse_manager.clear(stream_id)


# ── Main reader loop ──────────────────────────────────────────────────

# Track the last MongoDB ObjectId we've seen — so we only query newer docs.
from bson import ObjectId as _ObjectId

_last_oid: _ObjectId | None = None
_start_oid: _ObjectId | None = None   # where this process started reading


async def _starting_point(col) -> _ObjectId | None:
    """Continue from the saved position; on a first start, from the newest event
    (older events are shown on demand by load_history, never re-processed)."""
    try:
        saved = await review_store.get_position()
    except report_store.StoreUnavailable:
        saved = None
    if saved is not None:
        return saved
    newest = await asyncio.to_thread(lambda: col.find_one({}, sort=[("_id", -1)], projection={"_id": 1}))
    return newest["_id"] if newest else None


async def run_reader() -> None:
    """Poll MongoDB for new callback traces and process them.

    This function is designed to be launched via ``asyncio.create_task``
    during FastAPI's lifespan.  It retries on connection failures with
    exponential backoff so a MongoDB outage never kills the server.
    """
    global _last_oid, _start_oid, _reader_running
    backoff = 1  # seconds, doubles on each failure up to a cap
    client = None
    _reader_running = True

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
            if _last_oid is None:
                _last_oid = _start_oid = await _starting_point(col)
                logger.info("Reading traces after %s", _last_oid)
            _reader_started.set()

            while True:
                try:
                    # Only query documents newer than the last one we processed
                    query: dict = {}
                    if _last_oid is not None:
                        query["_id"] = {"$gt": _last_oid}

                    # pymongo blocks: query in a worker thread so the event loop stays free
                    docs = await asyncio.to_thread(
                        lambda q=query, c=col: list(c.find(q, sort=[("_id", 1)], limit=200)))
                    if docs:
                        new_count = await process_batch(docs)
                        if docs[-1].get("_id") is not None:
                            _last_oid = docs[-1]["_id"]  # processed: move the cursor on
                            try:
                                await review_store.set_position(_last_oid)
                            except report_store.StoreUnavailable:
                                logger.debug("Reader position not saved this time", exc_info=True)
                        if new_count:
                            logger.debug("Processed %d new trace events", new_count)

                except Exception:
                    logger.warning("MongoDB poll query failed — will retry", exc_info=True)

                await asyncio.sleep(config.TRACE_POLL_INTERVAL_MS / 1000)

        except asyncio.CancelledError:
            logger.info("Trace reader task cancelled — shutting down cleanly.")
            if client is not None:
                client.close()
            return
        except Exception:
            logger.exception("MongoDB connection lost — retrying in %ss", backoff)
            if client is not None:
                client.close()
                client = None
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
