"""FastAPI application for Component 04 — XAI Trace Collector.

Responsibilities:
  - Initialise the SQLite database on startup.
  - Launch the MongoDB trace reader as a background task.
  - Expose REST endpoints for querying stored traces and audit runs.
  - Serve SSE endpoints for live XAI "Thinking" timeline.

The reader runs alongside the ASGI server inside the same event
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
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.reporting import report_service
from app.services import database as db
from app.services import report_store, sse_manager, trace_reader

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

    # 2. Launch the MongoDB trace reader as a background task
    reader_task = asyncio.create_task(trace_reader.run_reader())
    logger.info("Trace reader background task launched.")

    yield  # ← server is running

    # 3. Graceful shutdown
    reader_task.cancel()
    try:
        await reader_task
    except asyncio.CancelledError:
        pass
    logger.info("Trace reader stopped.  Goodbye.")


# ── FastAPI app ────────────────────────────────────────────────────────

app = FastAPI(
    title="NOMOS Component 04 — XAI Trace Collector",
    description="Independent sidecar that captures, verifies, and stores "
                "execution traces from the multi-agent audit system via "
                "LangGraph BaseCallbackHandler events in MongoDB.",
    version="0.2.0",
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
        "architecture": "callback-mongodb-sidecar",
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


# ── Real-time SSE stream (XAI Thinking Timeline) ─────────────────────

@app.get("/xai/stream/{case_id}")
async def stream_xai(case_id: str, request: Request):
    """Server-Sent Events endpoint — pushes live XAI trace updates for a case.

    The frontend opens an EventSource connection to this URL.  Each time
    the trace reader picks up a new callback event from MongoDB, it is
    broadcast here in real time.
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


# Legacy SSE endpoint — kept for backward compatibility
@app.get("/traces/stream/{case_id}")
async def stream_traces(case_id: str, request: Request):
    """Alias for /xai/stream/{case_id} — backward compatible."""
    return await stream_xai(case_id, request)


# ── Final audit report (PDF, stored in MongoDB) ───────────────────────

class ReportRequest(BaseModel):
    """C3's request (Component-03/docs/c4_report_contract.md)."""
    audit_id: str | None = None   # "<case_id>:v<version>"
    case_id: str | None = None
    version: int | None = None


async def _generate(audit_id: str | None, case_id: str | None, version: int | None) -> dict:
    try:
        return await report_service.generate(audit_id, case_id, version)
    except report_service.ReportError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc


@app.post("/report/generate")
async def generate_report(body: ReportRequest):
    """Build the PDF for exactly the audit C3 names; reply with its download link."""
    return await _generate(body.audit_id, body.case_id, body.version)


@app.post("/report/generate/{case_id}")
async def generate_latest_report(case_id: str):
    """Older form (case id only): the report of the case's latest audit version."""
    return await _generate(None, case_id, None)


@app.get("/report/download/{filename}")
async def download_report(filename: str, download: bool = False):
    """Serve a report from object storage: shown in the browser, or saved with ?download=1.

    The link stays on C04, so C3 and the browser never need the storage address or keys."""
    if not report_store.REPORT_FILE.match(filename):
        raise HTTPException(status_code=404, detail=f"Report '{filename}' not found.")
    try:
        doc = await report_store.get_report(filename)
    except report_store.StoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"The report store is unavailable: {exc}") from exc
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Report '{filename}' not found.")
    try:
        chunks = await report_store.open_report(doc)
    except report_store.StoreUnavailable as exc:
        raise HTTPException(status_code=502, detail=f"Could not read the report from storage: {exc}") from exc
    if chunks is None:
        raise HTTPException(status_code=404, detail=f"Report '{filename}' is missing from storage.")
    disposition = "attachment" if download else "inline"
    headers = {"Content-Disposition": f'{disposition}; filename="{filename}"',
               "Cache-Control": "private, max-age=3600"}
    if doc.get("size_bytes"):
        headers["Content-Length"] = str(doc["size_bytes"])
    return StreamingResponse(chunks, media_type="application/pdf", headers=headers)


@app.get("/report/list/{case_id}")
async def list_reports(case_id: str, limit: int = 20):
    """Reports already generated for a case, newest first (no file contents)."""
    try:
        reports = await report_store.list_reports(case_id, min(max(limit, 1), 100))
    except report_store.StoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"The report store is unavailable: {exc}") from exc
    return {"case_id": case_id, "reports": [
        {**{k: v for k, v in r.items()
            if k not in ("_id", "sha256", "content_type", "bucket", "object_key", "storage")},
         "download_url": f"/report/download/{r['filename']}"} for r in reports]}
