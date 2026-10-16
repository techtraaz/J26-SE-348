import tempfile
import uuid
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

router = APIRouter(prefix="/kg", tags=["kg construction"])

# in memory is enough for the PoC; jobs are lost on restart
JOBS: dict[str, dict] = {}


class OCRIngestRequest(BaseModel):
    file: str
    result: ExtractionResult


def _run_job(job_id: str, doc: LoadedDocument, write: bool, max_chunks: int | None) -> None:
    job = JOBS[job_id]
    job.update(status="running", started_at=datetime.now(UTC).isoformat())
    try:
        result = service.build_pipeline(write=write, max_chunks=max_chunks).run(doc)
        job.update(status="done", summary=result.summary(), proposals=result.proposals)
    except Exception as exc:  # noqa: BLE001 - reported through the job, not raised into the worker
        job.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    job["finished_at"] = datetime.now(UTC).isoformat()


def _queue(background: BackgroundTasks, doc: LoadedDocument, write: bool,
           max_chunks: int | None) -> dict:
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"job_id": job_id, "file": doc.file, "code": doc.code, "source": doc.source,
                    "status": "queued", "write": write,
                    "queued_at": datetime.now(UTC).isoformat()}
    background.add_task(_run_job, job_id, doc, write, max_chunks)
    return JOBS[job_id]


@router.post("/ingest/pdf", status_code=202)
async def ingest_pdf(background: BackgroundTasks, file: Annotated[UploadFile, File()],
                     write: bool = True, max_chunks: int | None = None) -> dict:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Upload a .pdf file")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / Path(file.filename).name
        path.write_bytes(await file.read())
        try:
            doc = load_pdf(path)
        except Exception as exc:
            raise HTTPException(422, f"Could not read PDF: {exc}") from exc
    return _queue(background, doc, write, max_chunks)


@router.post("/ingest/ocr", status_code=202)
def ingest_ocr(body: OCRIngestRequest, background: BackgroundTasks, write: bool = True,
               max_chunks: int | None = None) -> dict:
    """Scanned documents already read by Component 01."""
    return _queue(background, load_extraction(body.result, body.file), write, max_chunks)


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
