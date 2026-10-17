"""The background task: one ExtractionRun, from queued to finished.

Design notes
- No database transaction is held open during OCR (it takes minutes); each
  database step is a short transaction of its own.
- Regions and pages are written in ONE final transaction, so a crash can
  never leave a half-written run behind. Progress counters are the only
  thing updated along the way.
- Failures never escape: they are recorded on the run (with developer
  detail) and on the document (with a stable code and a user-safe message).
"""

import logging
import time
import uuid

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.enums import DocumentStatus, RunStatus
from app.db.models import Document, ExtractionRun, Page, Region
from app.db.types import utcnow
from app.schemas.extraction import EngineInfo
from app.services.imaging import encode_png
from app.services.ingestion.models import IngestionError, PageImage
from app.services.ingestion.pipeline import ingest
from app.services.ocr.base import OCREngine, PageRecognition
from app.services.storage.base import Storage

logger = logging.getLogger(__name__)

SessionFactory = sessionmaker[Session]
_StoredPage = tuple[PageImage, PageRecognition, str, str | None]  # + storage keys

def process_run(
    run_id: uuid.UUID,
    *,
    session_factory: SessionFactory,
    storage: Storage,
    engine: OCREngine,
    settings: Settings,
) -> None:
    started = time.perf_counter()
    try:
        document_id, original_key = _begin(session_factory, run_id)
        ingested = ingest(
            storage.load(original_key), limits=settings.limits, pdf_dpi=settings.pdf_dpi
        )
        _set_progress(session_factory, run_id, total=len(ingested.pages), done=0)

        stored: list[_StoredPage] = []
        for page_image in ingested.pages:
            recognition = engine.recognize_page(page_image.image, page_image.page_number)
            original, ocr = _store_images(storage, document_id, page_image, recognition)
            stored.append((page_image, recognition, original, ocr))
            _set_progress(session_factory, run_id, total=len(ingested.pages), done=len(stored))

        _finish(
            session_factory,
            run_id,
            document_id,
            ingested.kind.value,
            stored,
            engine.info(),
            settings,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
    except IngestionError as err:
        logger.info("Run %s rejected by ingestion: %s", run_id, err.code)
        _fail(session_factory, run_id, err.code, err.message, err.message, started)
    except Exception as exc:
        logger.exception("Extraction run %s failed", run_id)
        _fail(
            session_factory,
            run_id,
            "processing_error",
            "Extraction failed unexpectedly. Please retry; if it keeps failing, contact support.",
            f"{type(exc).__name__}: {exc}",
            started,
        )

def _begin(session_factory: SessionFactory, run_id: uuid.UUID) -> tuple[uuid.UUID, str]:
    with session_factory() as db:
        run = db.get(ExtractionRun, run_id)
        document = db.get(Document, run.document_id) if run else None
        if run is None or document is None:
            raise LookupError(f"Run {run_id} or its document no longer exists")
        document.status = DocumentStatus.PROCESSING.value
        db.commit()
        return document.id, document.original_key

def _set_progress(session_factory: SessionFactory, run_id: uuid.UUID, total: int, done: int) -> None:
    with session_factory() as db:
        run = db.get(ExtractionRun, run_id)
        run.pages_total = total
        run.pages_done = done
        db.commit()

def _store_images(
    storage: Storage, document_id: uuid.UUID, page_image: PageImage, recognition: PageRecognition
) -> tuple[str, str | None]:
    base = f"documents/{document_id}/pages/{page_image.page_number}"
    original_key = f"{base}.original.png"
    storage.save(original_key, encode_png(page_image.image))

    # Boxes refer to the OCR-space image (decision D3). Store it separately
    # only when the engine's preprocessing actually changed the page.
    ocr_key = None
    if not np.array_equal(recognition.ocr_image, page_image.image):
        ocr_key = f"{base}.ocr.png"
        storage.save(ocr_key, encode_png(recognition.ocr_image))
    return original_key, ocr_key

def _finish(
    session_factory: SessionFactory,
    run_id: uuid.UUID,
    document_id: uuid.UUID,
    file_kind: str,
    stored: list[_StoredPage],
    info: EngineInfo,
    settings: Settings,
    elapsed_ms: float,
) -> None:
    with session_factory() as db:
        run = db.get(ExtractionRun, run_id)
        document = db.get(Document, document_id)
        existing = {
            p.page_number: p
            for p in db.scalars(select(Page).where(Page.document_id == document_id))
        }

        sequence = 0  # reading order across the whole run
        for page_image, recognition, original_key, ocr_key in stored:
            number = page_image.page_number
            page = existing.get(number) or Page(document_id=document_id, page_number=number)
            page.width = recognition.page.width
            page.height = recognition.page.height
            page.dpi = page_image.dpi
            page.original_image_key = original_key
            page.ocr_image_key = ocr_key
            db.add(page)
            db.flush()

            for line in recognition.page.lines:
                db.add(
                    Region(
                        run_id=run_id,
                        page_id=page.id,
                        sequence=sequence,
                        text=line.text,
                        confidence=line.confidence,  # raw, untouched (D4)
                        box=list(line.box),
                        polygon=[list(point) for point in line.polygon],
                        provenance=info.name,
                    )
                )
                sequence += 1

        run.status = RunStatus.SUCCEEDED.value
        run.finished_at = utcnow()
        run.elapsed_ms = elapsed_ms
        run.pages_total = run.pages_done = len(stored)
        run.engine_info = info.model_dump(mode="json")
        run.config = {"pdf_dpi": settings.pdf_dpi, "file_kind": file_kind}

        document.status = DocumentStatus.NEEDS_REVIEW.value
        document.page_count = len(stored)
        document.error_code = None
        document.error_message = None
        db.commit()

def _fail(
    session_factory: SessionFactory,
    run_id: uuid.UUID,
    code: str,
    message: str,
    detail: str,
    started: float,
) -> None:
    with session_factory() as db:
        run = db.get(ExtractionRun, run_id)
        if run is None:  # document deleted meanwhile; nothing to record
            return
        run.status = RunStatus.FAILED.value
        run.finished_at = utcnow()
        run.elapsed_ms = (time.perf_counter() - started) * 1000
        run.error = detail[:2000]

        document = db.get(Document, run.document_id)
        document.status = DocumentStatus.FAILED.value
        document.error_code = code
        document.error_message = message
        db.commit()