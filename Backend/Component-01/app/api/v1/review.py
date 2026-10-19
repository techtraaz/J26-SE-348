"""Review API (M4): the reviewer's draft of a document's lines."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi import Path as PathParam
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_db
from app.api.errors import ApiError
from app.db.models import Document
from app.schemas.review import ReviewDraftIn, ReviewDraftOut
from app.services.review import drafts
from app.services.review.drafts import DraftError

router = APIRouter(prefix="/documents", tags=["review"])

Db = Annotated[Session, Depends(get_db)]
DocumentId = Annotated[uuid.UUID, PathParam()]

_STATUS_BY_CODE = {
    "extraction_not_ready": 409,
    "document_verified": 409,
    "run_changed": 409,
    "draft_conflict": 409,
    "invalid_draft": 422,
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
