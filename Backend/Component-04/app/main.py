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
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from app.reporting import pdf_renderer
from app.services import database as db
from app.services import sse_manager
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

# ── CORS (allow the dashboard to talk to the API) ─────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static files & Dashboard ──────────────────────────────────────────
_STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the XAI Trace Dashboard."""
    index = _STATIC_DIR / "index.html"
    return HTMLResponse(content=index.read_text(encoding="utf-8"))


# ── Health check ───────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": "component-04-xai-trace-collector",
        "active_sse_cases": sse_manager.active_case_ids(),
    }


# ── Trace query endpoints ─────────────────────────────────────────────

@app.get("/runs")
async def list_runs(limit: int = 50):
    """Return the most recent audit runs."""
    runs = await db.get_runs(limit=limit)
    return {"runs": runs}


@app.get("/traces/{case_id}")
async def get_traces(case_id: str):
    """Return all completed traces for a case from SQLite, ordered by step."""
    traces = await db.get_traces_for_case(case_id)
    return {"case_id": case_id, "trace_count": len(traces), "traces": traces}


# ── Real-time SSE stream ──────────────────────────────────────────────

@app.get("/traces/stream/{case_id}")
async def stream_traces(case_id: str, request: Request):
    """Server-Sent Events endpoint — pushes live trace updates for a case.

    The frontend opens an EventSource connection to this URL.  Each time
    the subscriber persists a new trace, it is broadcast here in real time.
    """

    async def _event_generator():
        async for payload in sse_manager.subscribe(case_id):
            if await request.is_disconnected():
                break
            yield {
                "event": payload.get("event_type", "trace"),
                "data": json.dumps(payload),
            }

    return EventSourceResponse(_event_generator())


# ── PDF Report generation ─────────────────────────────────────────────

@app.post("/report/generate/{case_id}")
async def generate_report(case_id: str):
    """Generate a deterministic PDF audit report for the given case.

    Fetches verified traces from the Middle DB, fills the Jinja2 template,
    and renders a PDF via WeasyPrint.  Returns metadata with a download URL.
    """
    try:
        result = await pdf_renderer.generate_report(case_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {
        "status": "report_ready",
        "case_id": result["case_id"],
        "filename": result["filename"],
        "generated_at": result["generated_at"],
        "download_url": f"/report/download/{result['filename']}",
    }


@app.get("/report/download/{filename}")
async def download_report(filename: str):
    """Serve a previously generated PDF report as a file download."""
    reports_dir = Path(__file__).resolve().parent.parent / "reports"
    file_path = reports_dir / filename

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"Report '{filename}' not found.")

    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        filename=filename,
    )

