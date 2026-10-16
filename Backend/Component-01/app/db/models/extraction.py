import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import PipelineMode, RunStatus
from app.db.types import JsonType, utcnow


class ExtractionRun(Base):
    """One execution of a pipeline over a document. Immutable once finished,
    so runs with different engines/modes/settings can be compared (D5)."""

    __tablename__ = "extraction_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    pipeline_mode: Mapped[str] = mapped_column(String(20), default=PipelineMode.OCR_ONLY.value)
    # Engine name/version/settings/env flags/hardware, exactly as recorded by
    # the engine (EngineInfo), plus pipeline config such as PDF DPI.
    engine_info: Mapped[dict | None] = mapped_column(JsonType)
    config: Mapped[dict | None] = mapped_column(JsonType)
    status: Mapped[str] = mapped_column(String(20), default=RunStatus.QUEUED.value, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    elapsed_ms: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)

    document: Mapped["Document"] = relationship(back_populates="runs")  # noqa: F821
    regions: Mapped[list["Region"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="Region.sequence",
        passive_deletes=True,
    )


class Region(Base):
    """Machine output only: one recognized text region. Never edited; human
    changes live in corrections / review drafts / verified records (D2)."""

    __tablename__ = "regions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), index=True
    )
    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pages.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)  # reading order within the run
    text: Mapped[str] = mapped_column(Text)
    # Raw engine score, stored untouched (D4). Nullable for engines that
    # emit none (a Phase 2 VLM may not).
    confidence: Mapped[float | None] = mapped_column(Float)
    box: Mapped[list] = mapped_column(JsonType)  # [x1, y1, x2, y2]
    polygon: Mapped[list | None] = mapped_column(JsonType)  # [[x, y] x 4]
    provenance: Mapped[str] = mapped_column(String(50))  # engine that produced it
    escalated: Mapped[bool | None] = mapped_column(Boolean)  # Phase 3 routing
    # Reserved for the structuring stage (open decision O1).
    field_key: Mapped[str | None] = mapped_column(String(100))
    table_row: Mapped[int | None] = mapped_column(Integer)
    table_col: Mapped[int | None] = mapped_column(Integer)

    run: Mapped[ExtractionRun] = relationship(back_populates="regions")