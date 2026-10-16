"""TEMPORARY development endpoints (milestone M1).

They exercise ingestion + OCR + storage without a database. M2 replaces them
with the real documents API (upload -> background job -> stored regions).
"""

import uuid
from typing import Annotated, Literal

import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi import Path as PathParam
from fastapi.responses import Response
from pydantic import BaseModel

from app.api.deps import get_engine, get_settings, get_storage
from app.core.config import Settings
from app.schemas.extraction import EngineInfo, ExtractionResult, PageResult
from app.services.imaging import encode_png
from app.services.ingestion.pipeline import ingest
from app.services.ocr.base import OCREngine
from app.services.storage.base import Storage

router = APIRouter(prefix="/dev", tags=["dev (temporary)"])

DocumentId = Annotated[str, PathParam(pattern=r"^[0-9a-f]{32}$")]

class PageOut(PageResult):
    image_url: str

class DevExtractResponse(BaseModel):
    document_id: str
    kind: str
    sha256: str
    engine: EngineInfo
    pages: list[PageOut]

def _image_url(document_id: str, page_number: int) -> str:
    return f"/api/v1/dev/documents/{document_id}/pages/{page_number}/image"

@router.post("/extract", response_model=DevExtractResponse)
def extract(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    engine: Annotated[OCREngine, Depends(get_engine)],
    storage: Annotated[Storage, Depends(get_storage)],
    file: UploadFile = File(...),
) -> DevExtractResponse:
    # Plain `def`, so FastAPI runs this in a worker thread and the event loop
    # stays free while OCR (slow, CPU-bound) runs.
    # Read one byte past the limit: ingest() then rejects oversized uploads
    # without us loading an arbitrarily large body into memory.
    data = file.file.read(settings.max_file_bytes + 1)
    ingested = ingest(data, limits=settings.limits, pdf_dpi=settings.pdf_dpi)

    # One inference at a time: keeps latency measurements clean
    # and avoids sharing a model across threads.
    with request.app.state.engine_lock:
        recognitions = [
            engine.recognize_page(p.image, p.page_number) for p in ingested.pages
        ]

    document_id = uuid.uuid4().hex
    base = f"documents/{document_id}"
    storage.save(f"{base}/original.{ingested.kind.value}", data)

    for page_image, recognition in zip(ingested.pages, recognitions):
        n = page_image.page_number
        storage.save(f"{base}/pages/{n}.original.png", encode_png(page_image.image))
        # Store the OCR-space image only when it differs from the page image
        # (engine preprocessing changed it); boxes refer to it.
        if not np.array_equal(recognition.ocr_image, page_image.image):
            storage.save(f"{base}/pages/{n}.ocr.png", encode_png(recognition.ocr_image))

    result = ExtractionResult(engine=engine.info(), pages=[r.page for r in recognitions])
    storage.save(f"{base}/result.json", result.model_dump_json().encode("utf-8"))

    return DevExtractResponse(
        document_id=document_id,
        kind=ingested.kind.value,
        sha256=ingested.sha256,
        engine=result.engine,
        pages=[
            PageOut(**page.model_dump(), image_url=_image_url(document_id, page.page_number))
            for page in result.pages
        ],
    )

@router.get("/documents/{document_id}/pages/{page_number}/image")
def page_image(
    document_id: DocumentId,
    page_number: Annotated[int, PathParam(ge=1)],
    storage: Annotated[Storage, Depends(get_storage)],
    variant: Literal["ocr", "original"] = "ocr",
) -> Response:
    base = f"documents/{document_id}/pages/{page_number}"
    keys = [f"{base}.ocr.png", f"{base}.original.png"] if variant == "ocr" else [f"{base}.original.png"]
    for key in keys:
        if storage.exists(key):
            return Response(storage.load(key), media_type="image/png")
    raise HTTPException(status_code=404, detail="Page image not found.")