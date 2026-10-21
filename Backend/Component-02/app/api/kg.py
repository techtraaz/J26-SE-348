import logging
import tempfile
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.construction import service
from app.construction.documents import LoadedDocument
from app.construction.loaders import load_extraction, load_pdf
from app.schemas.extraction import ExtractionResult

log = logging.getLogger("kg.jobs")

router = APIRouter(prefix="/kg", tags=["kg construction"])

# in memory is enough for the PoC; jobs are lost on restart
JOBS: dict[str, dict] = {}


class OCRIngestRequest(BaseModel):
    file: str
    result: ExtractionResult
    code: str | None = None


def _totals() -> dict | None:
    try:
        return service.graph_totals()
    except Exception:
        log.warning("could not count graph totals", exc_info=True)
        return None


def _run_job(job_id: str, doc: LoadedDocument, write: bool, max_chunks: int | None,
             on_done: Callable[[dict], None] | None = None) -> None:
    job = JOBS[job_id]
    job.update(status="running", started_at=datetime.now(UTC).isoformat())

    # stage = what runs now, stages_done = what finished; progress = paragraphs sent to the LLM
    def progress(stage: str, info: dict) -> None:
        if stage != job.get("stage"):
            if job.get("stage"):
                job.setdefault("stages_done", []).append(job["stage"])
            job["stage"], job["progress"] = stage, None
        if info:
            job["progress"] = info

    try:
        before = _totals() if write else None
        result = service.build_pipeline(write=write, max_chunks=max_chunks).run(doc, progress)
        job.update(status="done", kind=result.kind, summary=result.summary(),
                   proposals=result.proposals, changes=result.changes,
                   totals={"before": before, "after": _totals() if write else None})
    except Exception as exc:  # noqa: BLE001 - reported through the job, not raised into the worker
        job.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    else:
        if job.get("stage"):
            job.setdefault("stages_done", []).append(job["stage"])
        job["stage"] = None
    job["finished_at"] = datetime.now(UTC).isoformat()
    if on_done:
        try:
            on_done(job)
        except Exception:
            log.warning("job %s: saving the result failed", job_id, exc_info=True)


def _queue(background: BackgroundTasks, doc: LoadedDocument, write: bool,
           max_chunks: int | None, on_done: Callable[[dict], None] | None = None,
           **extra) -> dict:
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"job_id": job_id, "file": doc.file, "code": doc.code, "source": doc.source,
                    "status": "queued", "write": write,
                    "queued_at": datetime.now(UTC).isoformat(), **extra}
    background.add_task(_run_job, job_id, doc, write, max_chunks, on_done)
    return JOBS[job_id]


@router.post("/ingest/pdf", status_code=202)
async def ingest_pdf(background: BackgroundTasks, file: Annotated[UploadFile, File()],
                     write: bool = True, max_chunks: int | None = None,
                     code: str | None = None) -> dict:
    """code, e.g. "LKAS 18", is only needed when neither the file name nor the title page has it."""
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Upload a .pdf file")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / Path(file.filename).name
        path.write_bytes(await file.read())
        try:
            doc = load_pdf(path, code)
        except Exception as exc:
            raise HTTPException(422, f"Could not read PDF: {exc}") from exc
    return _queue(background, doc, write, max_chunks)


@router.post("/ingest/ocr", status_code=202)
def ingest_ocr(body: OCRIngestRequest, background: BackgroundTasks, write: bool = True,
               max_chunks: int | None = None) -> dict:
    """Scanned documents already read by Component 01."""
    return _queue(background, load_extraction(body.result, body.file, body.code), write, max_chunks)


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    if job_id not in JOBS:
        raise HTTPException(404, f"Unknown job '{job_id}'")
    return JOBS[job_id]


@router.get("/jobs")
def list_jobs() -> list[dict]:
    return sorted(JOBS.values(), key=lambda j: j["queued_at"], reverse=True)


@router.get("/pipeline", response_class=PlainTextResponse)
def get_pipeline_diagram() -> str:
    return service.build_pipeline(write=False).mermaid()
