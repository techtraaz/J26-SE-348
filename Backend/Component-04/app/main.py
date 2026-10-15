"""FastAPI application for Component 04 — XAI Trace Collector.

Responsibilities:
  - Initialise the SQLite database on startup.
  - Launch the Redis subscriber as a background task.
  - Expose REST endpoints for querying stored traces and audit runs.

The subscriber runs alongside the ASGI server inside the same event
loop but never blocks the HTTP request path.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.services import database as db
from app.services import subscriber

# ── Logging ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-18s  %(levelname)-5s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("c04.main")


# ── Lifespan — startup / shutdown ─────────────────────────────────────

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Run once at startup, yield for the server's lifetime, clean up on exit."""

    # 1. Create tables if missing
    await db.init_db()
    logger.info("Database ready.")

    # 2. Launch the Redis listener as a background task
    listener_task = asyncio.create_task(subscriber.run_listener())
    logger.info("Subscriber background task launched.")

    yield  # ← server is running

    # 3. Graceful shutdown
    listener_task.cancel()
    try:
        await listener_task
    except asyncio.CancelledError:
        pass
    logger.info("Subscriber stopped.  Goodbye.")


# ── FastAPI app ────────────────────────────────────────────────────────

app = FastAPI(
    title="NOMOS Component 04 — XAI Trace Collector",
    description="Passive observer that captures, verifies, and stores execution traces from the multi-agent audit system.",
    version="0.1.0",
    lifespan=lifespan,
)


# ── Health check ───────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"ok": True, "service": "component-04-xai-trace-collector"}


# ── Trace query endpoints ─────────────────────────────────────────────

@app.get("/runs")
async def list_runs(limit: int = 50):
    """Return the most recent audit runs."""
    runs = await db.get_runs(limit=limit)
    return {"runs": runs}


@app.get("/traces/{case_id}")
async def get_traces(case_id: str):
    """Return all enriched traces for a given case, ordered by step."""
    traces = await db.get_traces_for_case(case_id)
    return {"case_id": case_id, "trace_count": len(traces), "traces": traces}
