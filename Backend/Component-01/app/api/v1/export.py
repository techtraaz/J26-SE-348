"""Export API (M5): download a verified record (contract 0.1)."""

import json
import uuid
from pathlib import PurePath
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from fastapi import Path as PathParam
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.errors import ApiError
from app.db.models import Document
from app.services.export import contract_v1
from app.services.review import confirm
from app.services.review.drafts import DraftError

router = APIRouter(prefix="/documents", tags=["export"])

Db = Annotated[Session, Depends(get_db)]
DocumentId = Annotated[uuid.UUID, PathParam()]

_MEDIA_TYPES = {"json": "application/json", "csv": "text/csv; charset=utf-8"}


@router.get("/{document_id}/export")
def export_record(
    document_id: DocumentId,
    db: Db,
    version: Annotated[int | None, Query(ge=1)] = None,
    format: Literal["json", "csv"] = "json",
) -> Response:
    """The latest (or a given) verified version as a file: JSON in the
    contract shape with `schema_version`, or CSV with one row per line."""
    document = db.get(Document, document_id)
    if document is None:
        raise ApiError(404, "document_not_found", "Document not found.")
    try:
        record = confirm.get_record(db, document, version)
    except DraftError as exc:
        raise ApiError(404, exc.code, exc.message) from None

    if format == "csv":
        body = contract_v1.to_csv(record)
    else:
        body = json.dumps(contract_v1.to_json(record), ensure_ascii=False, indent=2)
    filename = f"{PurePath(document.filename).stem}-v{record.version}.{format}"
    return Response(
        content=body,
        media_type=_MEDIA_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
