import uuid
from datetime import datetime

from sqlalchemy import (
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import JsonType, UtcDateTime, utcnow

# Audit data is deliberately protected: a document with verified records or
# corrections cannot be deleted as a side effect (ondelete RESTRICT). Deleting
# verified data must be an explicit decision, not a cascade.


class ReviewDraft(Base):
    """Autosave target while a human is reviewing."""

    __tablename__ = "review_drafts"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    based_on_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE")
    )
    data: Mapped[dict] = mapped_column(JsonType)
    # Optimistic concurrency: a save must carry the version it was based on.
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), default=utcnow, onupdate=utcnow
    )


class VerifiedRecord(Base):
    """Immutable confirmed version. This is what downstream reads."""

    __tablename__ = "verified_records"
    __table_args__ = (UniqueConstraint("document_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)  # 1, 2, 3, ...
    based_on_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="RESTRICT")
    )
    data: Mapped[dict] = mapped_column(JsonType)
    confirmed_by: Mapped[str | None] = mapped_column(String(100))
    confirmed_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)


class Correction(Base):
    """Audit log of every human action, and labelled data for calibration
    analysis. `source` tags how trustworthy the label is: demo edits are not
    clean ground truth."""

    __tablename__ = "corrections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), index=True
    )
    region_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("regions.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(30))  # edit_text, accept, delete, add, move_box
    before: Mapped[dict | None] = mapped_column(JsonType)
    after: Mapped[dict | None] = mapped_column(JsonType)
    source: Mapped[str] = mapped_column(String(20), default="demo")
    at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    by: Mapped[str | None] = mapped_column(String(100))