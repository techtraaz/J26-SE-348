"""Single entry point: uploaded bytes -> ordered list of BGR page images.

Everything downstream (OCR, VLM, evaluation) consumes PageImage objects and
never sees the original file format.
"""

import hashlib

from app.services.ingestion.detect import detect_kind
from app.services.ingestion.load_image import load_image_pages
from app.services.ingestion.models import (
    DEFAULT_PDF_DPI,
    FileKind,
    IngestionError,
    IngestionLimits,
    IngestionResult,
)
from app.services.ingestion.rasterize_pdf import rasterize_pdf

def validate_upload(data: bytes, limits: IngestionLimits) -> FileKind:
    """The cheap checks (size, content type) that can reject an upload
    immediately, before any page is decoded or rasterized."""
    if len(data) > limits.max_file_bytes:
        raise IngestionError(
            "too_large",
            f"The file is {len(data) / 1_048_576:.1f} MB; "
            f"the limit is {limits.max_file_bytes // 1_048_576} MB.",
        )
    return detect_kind(data)

def ingest(
    data: bytes,
    *,
    limits: IngestionLimits | None = None,
    pdf_dpi: int = DEFAULT_PDF_DPI,
) -> IngestionResult:
    if not 50 <= pdf_dpi <= 600:
        raise ValueError(f"pdf_dpi must be between 50 and 600, got {pdf_dpi}")
    limits = limits or IngestionLimits()

    kind = validate_upload(data, limits)
    if kind is FileKind.PDF:
        pages = rasterize_pdf(data, pdf_dpi, limits)
    else:
        pages = load_image_pages(data, kind, limits)

    return IngestionResult(kind=kind, sha256=hashlib.sha256(data).hexdigest(), pages=pages)