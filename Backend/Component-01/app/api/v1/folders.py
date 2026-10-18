"""Folders API: a Drive-style tree for organizing documents."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.errors import ApiError
from app.db.models import Document, Folder
from app.schemas.folders import (
    BreadcrumbItem,
    FolderCreate,
    FolderDetail,
    FolderList,
    FolderOut,
    FolderRename,
)

router = APIRouter(prefix="/folders", tags=["folders"])

Db = Annotated[Session, Depends(get_db)]
_MAX_DEPTH = 50  # guard for the breadcrumb walk


def _get_folder(db: Session, folder_id: uuid.UUID) -> Folder:
    folder = db.get(Folder, folder_id)
    if folder is None:
        raise ApiError(404, "folder_not_found", "Folder not found.")
    return folder

def _counts(db: Session, folder_ids: list[uuid.UUID]) -> tuple[dict, dict]:
    """Direct sub-folder and document counts for each folder id."""
    sub = dict(
        db.execute(
            select(Folder.parent_id, func.count())
            .where(Folder.parent_id.in_(folder_ids))
            .group_by(Folder.parent_id)
        ).all()
    )
    docs = dict(
        db.execute(
            select(Document.folder_id, func.count())
            .where(Document.folder_id.in_(folder_ids))
            .group_by(Document.folder_id)
        ).all()
    )
    return sub, docs

def _out(folders: list[Folder], db: Session) -> list[FolderOut]:
    sub, docs = _counts(db, [f.id for f in folders]) if folders else ({}, {})
    return [
        FolderOut(
            id=f.id,
            parent_id=f.parent_id,
            name=f.name,
            created_at=f.created_at,
            folder_count=sub.get(f.id, 0),
            document_count=docs.get(f.id, 0),
        )
        for f in folders
    ]

def _ensure_unique_name(
    db: Session, parent_id: uuid.UUID | None, name: str, exclude: uuid.UUID | None = None
) -> None:
    """Names are unique per parent, ignoring case (like a file manager)."""
    stmt = select(Folder.id).where(
        Folder.parent_id == parent_id if parent_id is not None else Folder.parent_id.is_(None),
        func.lower(Folder.name) == name.lower(),
    )
    if exclude is not None:
        stmt = stmt.where(Folder.id != exclude)
    if db.scalar(stmt) is not None:
        raise ApiError(409, "folder_exists", "A folder with this name already exists here.")

def _breadcrumbs(db: Session, folder: Folder) -> list[BreadcrumbItem]:
    path: list[BreadcrumbItem] = []
    current: Folder | None = folder
    while current is not None and len(path) < _MAX_DEPTH:
        path.append(BreadcrumbItem(id=current.id, name=current.name))
        current = db.get(Folder, current.parent_id) if current.parent_id else None
    return path[::-1]

@router.post("", status_code=201, response_model=FolderOut)
def create_folder(body: FolderCreate, response: Response, db: Db) -> FolderOut:
    if body.parent_id is not None:
        _get_folder(db, body.parent_id)
    _ensure_unique_name(db, body.parent_id, body.name)

    folder = Folder(name=body.name, parent_id=body.parent_id)
    db.add(folder)
    db.commit()
    response.headers["Location"] = f"/api/v1/folders/{folder.id}"
    return _out([folder], db)[0]

@router.get("", response_model=FolderList)
def list_folders(db: Db, parent_id: uuid.UUID | None = None) -> FolderList:
    """Children of `parent_id`; the root level when it is omitted."""
    if parent_id is not None:
        _get_folder(db, parent_id)
    stmt = select(Folder).where(
        Folder.parent_id == parent_id if parent_id is not None else Folder.parent_id.is_(None)
    )
    folders = db.scalars(stmt.order_by(func.lower(Folder.name), Folder.id)).all()
    return FolderList(items=_out(list(folders), db))

@router.get("/{folder_id}", response_model=FolderDetail)
def get_folder(folder_id: uuid.UUID, db: Db) -> FolderDetail:
    folder = _get_folder(db, folder_id)
    return FolderDetail(**_out([folder], db)[0].model_dump(), breadcrumbs=_breadcrumbs(db, folder))

@router.patch("/{folder_id}", response_model=FolderOut)
def rename_folder(folder_id: uuid.UUID, body: FolderRename, db: Db) -> FolderOut:
    folder = _get_folder(db, folder_id)
    _ensure_unique_name(db, folder.parent_id, body.name, exclude=folder.id)
    folder.name = body.name
    db.commit()
    return _out([folder], db)[0]

@router.delete("/{folder_id}", status_code=204)
def delete_folder(folder_id: uuid.UUID, db: Db) -> Response:
    """Only empty folders can be deleted, so no document is lost by accident."""
    folder = _get_folder(db, folder_id)
    sub, docs = _counts(db, [folder.id])
    if sub.get(folder.id) or docs.get(folder.id):
        raise ApiError(409, "folder_not_empty", "Only empty folders can be deleted.")
    db.delete(folder)
    db.commit()
    return Response(status_code=204)