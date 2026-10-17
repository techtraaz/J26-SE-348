"""Importing this package registers every table on Base.metadata (Alembic
and create_all rely on that)."""

from app.db.models.document import Document, Page
from app.db.models.extraction import ExtractionRun, Region
from app.db.models.folder import Folder
from app.db.models.review import Correction, ReviewDraft, VerifiedRecord

__all__ = [
    "Correction",
    "Document",
    "ExtractionRun",
    "Folder",
    "Page",
    "Region",
    "ReviewDraft",
    "VerifiedRecord",
]