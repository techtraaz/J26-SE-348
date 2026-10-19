"""Review API: the reviewer's draft (M4), confirmation and verified versions (M5)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi import Path as PathParam
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_db
from app.api.errors import ApiError
from app.db.models import Document
from app.schemas.review import (
    ConfirmIn,
    ReviewDraftIn,
    ReviewDraftOut,
    VerifiedRecordOut,
)
from app.services.review import confirm, drafts
from app.services.review.drafts import DraftError

router = APIRouter(prefix="/documents", tags=["review"])

Db = Annotated[Session, Depends(get_db)]
DocumentId = Annotated[uuid.UUID, PathParam()]

_STATUS_BY_CODE = {
    "extraction_not_ready": 409,
    "document_verified": 409,
    "already_verified": 409,
    "not_reopenable": 409,
    "run_changed": 409,
    "draft_conflict": 409,
    "invalid_draft": 422,
    "not_verified": 404,
    "version_not_found": 404,
}


def _get_document(db: Session, document_id: uuid.UUID) -> Document:
    document = db.get(
        Document,
        document_id,
        options=[selectinload(Document.runs), selectinload(Document.pages)],
    )
    if document is None:
        raise ApiError(404, "document_not_found", "Document not found.")
    return document


def _api_error(exc: DraftError) -> ApiError:
    return ApiError(_STATUS_BY_CODE.get(exc.code, 422), exc.code, exc.message)


@router.get("/{document_id}/review", response_model=ReviewDraftOut)
def get_review(document_id: DocumentId, db: Db) -> ReviewDraftOut:
    """The saved draft, or one seeded from the latest successful run (version 0)."""
    try:
        return drafts.get_draft(db, _get_document(db, document_id))
    except DraftError as exc:
        raise _api_error(exc) from None


@router.put("/{document_id}/review", response_model=ReviewDraftOut)
def save_review(document_id: DocumentId, payload: ReviewDraftIn, db: Db) -> ReviewDraftOut:
    """Replace the draft. `version` must be the version the edit was based on;
    a stale version gets 409 draft_conflict."""
    try:
        return drafts.save_draft(db, _get_document(db, document_id), payload)
    except DraftError as exc:
        raise _api_error(exc) from None


@router.post("/{document_id}/confirm", status_code=201, response_model=VerifiedRecordOut)
def confirm_review(document_id: DocumentId, payload: ConfirmIn, db: Db) -> VerifiedRecordOut:
    """Freeze the draft at `version` as the next verified version. Lines nobody
    acted on are accepted; every human action is logged in corrections."""
    try:
        return confirm.confirm(db, _get_document(db, document_id), payload.version)
    except DraftError as exc:
        raise _api_error(exc) from None


@router.post("/{document_id}/reopen", status_code=204)
def reopen_review(document_id: DocumentId, db: Db) -> Response:
    """Return a verified document to review; its verified versions stay as they are."""
    try:
        confirm.reopen(db, _get_document(db, document_id))
    except DraftError as exc:
        raise _api_error(exc) from None
    return Response(status_code=204)


@router.get("/{document_id}/verified", response_model=VerifiedRecordOut)
def get_verified(document_id: DocumentId, db: Db) -> VerifiedRecordOut:
    """The latest verified version (contract 0.x, read by Component 03)."""
    try:
        return confirm.get_record(db, _get_document(db, document_id))
    except DraftError as exc:
        raise _api_error(exc) from None


@router.get("/{document_id}/verified/{version}", response_model=VerifiedRecordOut)
def get_verified_version(
    document_id: DocumentId, version: Annotated[int, PathParam(ge=1)], db: Db
) -> VerifiedRecordOut:
    """One verified version, by number (1, 2, 3, ...)."""
    try:
        return confirm.get_record(db, _get_document(db, document_id), version)
    except DraftError as exc:
        raise _api_error(exc) from None
