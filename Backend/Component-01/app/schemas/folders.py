import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, StringConstraints

FolderName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]

class FolderCreate(BaseModel):
    name: FolderName
    parent_id: uuid.UUID | None = None

class FolderRename(BaseModel):
    name: FolderName

class FolderOut(BaseModel):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    created_at: datetime
    folder_count: int  # direct sub-folders
    document_count: int  # direct documents

class BreadcrumbItem(BaseModel):
    id: uuid.UUID
    name: str

class FolderDetail(FolderOut):
    # Root-to-this-folder path, this folder last.
    breadcrumbs: list[BreadcrumbItem]

class FolderList(BaseModel):
    items: list[FolderOut]