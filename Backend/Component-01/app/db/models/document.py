import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import DocumentSource, DocumentStatus
from app.db.types import UtcDateTime, utcnow

if TYPE_CHECKING:  # circular at runtime; SQLAlchemy resolves the name lazily
    from app.db.models.extraction import ExtractionRun

class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("folders.id", ondelete="SET NULL"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    original_key: Mapped[str] = mapped_column(String(500))  # storage key of the upload
    status: Mapped[str] = mapped_column(
        String(20), default=DocumentStatus.UPLOADED.value, index=True
    )
    page_count: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(20), default=DocumentSource.DEMO.value)
    # Set when status == failed (stable code + user-safe message).
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(Text)
    # Nullable until authentication exists (plan O3).
    created_by: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), default=utcnow, onupdate=utcnow
    )

    pages: Mapped[list["Page"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Page.page_number",
        passive_deletes=True,
    )
    runs: Mapped[list["ExtractionRun"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="ExtractionRun.created_at",
        passive_deletes=True,
    )

class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int] = mapped_column(Integer)  # 1-based
    # Pixel size of the OCR-space image: region coordinates refer to it (D3).
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    dpi: Mapped[int | None] = mapped_column(Integer)  # set for rasterized PDFs
    original_image_key: Mapped[str] = mapped_column(String(500))
    # Only when the engine's preprocessing produced a different image.
    ocr_image_key: Mapped[str | None] = mapped_column(String(500))

    document: Mapped[Document] = relationship(back_populates="pages")