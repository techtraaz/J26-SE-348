"""Documents API: upload, list, status, extraction results, page images."""

import hashlib
import uuid
from pathlib import PurePath
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from fastapi import Path as PathParam
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_db, get_settings, get_storage
from app.api.errors import ApiError
from app.core.config import Settings
from app.db.enums import DocumentSource, DocumentStatus, RunStatus
from app.db.models import Document, ExtractionRun, Folder, Page, Region
from app.schemas.documents import (
    DocumentDetail,
    DocumentList,
    DocumentOut,
    ExtractionOut,
    PageOut,
    RegionOut,
    RunSummary,
)
from app.services.ingestion.pipeline import validate_upload
from app.services.storage.base import Storage

router = APIRouter(prefix="/documents", tags=["documents"])

Db = Annotated[Session, Depends(get_db)]
DocumentId = Annotated[uuid.UUID, PathParam()]


# ---- helpers ---------------------------------------------------------------


def _latest_run(document: Document) -> ExtractionRun | None:
    return max(document.runs, key=lambda r: (r.created_at, str(r.id)), default=None)


def _run_summary(run: ExtractionRun) -> RunSummary:
    return RunSummary(
        id=run.id,
        status=run.status,
        pipeline_mode=run.pipeline_mode,
        engine=(run.engine_info or {}).get("name"),
        pages_total=run.pages_total,
        pages_done=run.pages_done or 0,
        elapsed_ms=run.elapsed_ms,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def _document_fields(document: Document) -> dict:
    latest = _latest_run(document)
    return {
        "id": document.id,
        "folder_id": document.folder_id,
        "filename": document.filename,
        "mime": document.mime,
        "sha256": document.sha256,
        "status": document.status,
        "page_count": document.page_count,
        "source": document.source,
        "error_code": document.error_code,
        "error_message": document.error_message,
        "created_at": document.created_at,
        "updated_at": document.updated_at,
        "latest_run": _run_summary(latest) if latest else None,
    }


def _image_url(document_id: uuid.UUID, page_number: int) -> str:
    return f"/api/v1/documents/{document_id}/pages/{page_number}/image"


def _page_out(page: Page) -> PageOut:
    return PageOut(
        page_number=page.page_number,
        width=page.width,
        height=page.height,
        dpi=page.dpi,
        image_url=_image_url(page.document_id, page.page_number),
    )


def _get_document(db: Session, document_id: uuid.UUID) -> Document:
    document = db.get(
        Document,
        document_id,
        options=[selectinload(Document.runs), selectinload(Document.pages)],
    )
    if document is None:
        raise ApiError(404, "document_not_found", "Document not found.")
    return document


# ---- endpoints -------------------------------------------------------------


@router.post("", status_code=202, response_model=DocumentOut)
def upload_document(
    response: Response,
    db: Db,
    storage: Annotated[Storage, Depends(get_storage)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: UploadFile = File(...),
    folder_id: Annotated[uuid.UUID | None, Form()] = None,
    source: Annotated[DocumentSource, Form()] = DocumentSource.DEMO,
) -> DocumentOut:
    """Accept an upload and queue extraction. Returns immediately (202); poll
    GET /documents/{id} for status and progress."""
    # Read one byte past the limit so an oversized body is rejected without
    # loading it all into memory.
    data = file.file.read(settings.max_file_bytes + 1)
    kind = validate_upload(data, settings.limits)  # raises IngestionError -> 4xx

    if folder_id is not None and db.get(Folder, folder_id) is None:
        raise ApiError(404, "folder_not_found", "Folder not found.")

    document_id = uuid.uuid4()
    original_key = f"documents/{document_id}/original.{kind.value}"
    storage.save(original_key, data)

    # Strip any client-supplied path; only the bare file name is kept.
    filename = PurePath(file.filename or "upload").name[:255] or "upload"
    document = Document(
        id=document_id,
        folder_id=folder_id,
        filename=filename,
        mime=kind.mime,
        sha256=hashlib.sha256(data).hexdigest(),
        original_key=original_key,
        source=source.value,
    )
    document.runs.append(ExtractionRun())  # status "queued": the worker picks it up
    db.add(document)
    db.commit()

    response.headers["Location"] = f"/api/v1/documents/{document_id}"
    return DocumentOut(**_document_fields(document))


@router.get("", response_model=DocumentList)
def list_documents(
    db: Db,
    folder_id: uuid.UUID | None = None,
    status: DocumentStatus | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentList:
    filters = []
    if folder_id is not None:
        filters.append(Document.folder_id == folder_id)
    if status is not None:
        filters.append(Document.status == status.value)
    if q:
        filters.append(Document.filename.icontains(q, autoescape=True))

    total = db.scalar(select(func.count()).select_from(Document).where(*filters)) or 0
    documents = db.scalars(
        select(Document)
        .where(*filters)
        .options(selectinload(Document.runs))
        .order_by(Document.created_at.desc(), Document.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return DocumentList(
        items=[DocumentOut(**_document_fields(d)) for d in documents],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(document_id: DocumentId, db: Db) -> DocumentDetail:
    document = _get_document(db, document_id)
    return DocumentDetail(
        **_document_fields(document),
        pages=[_page_out(p) for p in document.pages],
    )


@router.post("/{document_id}/retry", status_code=202, response_model=DocumentOut)
def retry_document(document_id: DocumentId, db: Db) -> DocumentOut:
    """Queue a new extraction run for a failed document."""
    document = _get_document(db, document_id)
    if document.status != DocumentStatus.FAILED.value:
        raise ApiError(409, "not_retryable", "Only failed documents can be retried.")

    document.status = DocumentStatus.UPLOADED.value
    document.error_code = None
    document.error_message = None
    document.runs.append(ExtractionRun())
    db.commit()
    return DocumentOut(**_document_fields(document))


@router.get("/{document_id}/extraction", response_model=ExtractionOut)
def get_extraction(document_id: DocumentId, db: Db) -> ExtractionOut:
    """Regions from the latest successful run, plus page geometry."""
    document = _get_document(db, document_id)
    run = max(
        (r for r in document.runs if r.status == RunStatus.SUCCEEDED.value),
        key=lambda r: (r.created_at, str(r.id)),
        default=None,
    )
    if run is None:
        raise ApiError(
            409,
            "extraction_not_ready",
            f"No extraction result yet (document status: {document.status}).",
        )

    page_numbers = {p.id: p.page_number for p in document.pages}
    regions = db.scalars(
        select(Region).where(Region.run_id == run.id).order_by(Region.sequence)
    ).all()
    return ExtractionOut(
        document_id=document.id,
        run=_run_summary(run),
        pages=[_page_out(p) for p in document.pages],
        regions=[
            RegionOut(
                id=r.id,
                sequence=r.sequence,
                page_number=page_numbers[r.page_id],
                text=r.text,
                confidence=r.confidence,
                box=r.box,
                polygon=r.polygon,
                provenance=r.provenance,
                escalated=r.escalated,
                field_key=r.field_key,
            )
            for r in regions
        ],
    )


@router.get("/{document_id}/pages/{page_number}/image")
def get_page_image(
    document_id: DocumentId,
    page_number: Annotated[int, PathParam(ge=1)],
    db: Db,
    storage: Annotated[Storage, Depends(get_storage)],
    variant: Literal["ocr", "original"] = "ocr",
) -> Response:
    """The page image. `ocr` (default) is the image region boxes refer to."""
    page = db.scalar(
        select(Page).where(Page.document_id == document_id, Page.page_number == page_number)
    )
    if page is None:
        raise ApiError(404, "page_not_found", "Page not found.")

    key = page.original_image_key
    if variant == "ocr" and page.ocr_image_key:
        key = page.ocr_image_key
    try:
        return Response(storage.load(key), media_type="image/png")
    except FileNotFoundError:
        raise ApiError(404, "image_missing", "The page image is missing from storage.") from None