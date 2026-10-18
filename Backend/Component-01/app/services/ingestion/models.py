"""Types shared by the ingestion layer."""

from dataclasses import dataclass
from enum import Enum

import numpy as np

# Rasterization DPI for PDFs. A recorded, tunable variable (it affects both
# OCR accuracy and speed; an A4 page is ~2.2 MP at 150 DPI, ~3.9 MP at 200).
DEFAULT_PDF_DPI = 150

class FileKind(str, Enum):
    PNG = "png"
    JPEG = "jpeg"
    TIFF = "tiff"
    BMP = "bmp"
    WEBP = "webp"
    PDF = "pdf"

    @property
    def mime(self) -> str:
        return {
            "png": "image/png",
            "jpeg": "image/jpeg",
            "tiff": "image/tiff",
            "bmp": "image/bmp",
            "webp": "image/webp",
            "pdf": "application/pdf",
        }[self.value]

@dataclass(frozen=True)
class IngestionLimits:
    max_file_bytes: int = 25 * 1024 * 1024
    max_pages: int = 20
    max_pixels_per_page: int = 40_000_000

class IngestionError(Exception):
    """A user-facing ingestion failure.

    `code` is stable and machine-readable (the API maps it to a status code
    and the frontend can branch on it); `message` is safe to show to a user.
    Codes: empty_file, unsupported_type, too_large, too_many_pages,
    image_too_large, password_protected, corrupt.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

@dataclass
class PageImage:
    page_number: int  # 1-based
    image: np.ndarray  # BGR, uint8, shape (height, width, 3)
    dpi: int | None  # rasterization DPI for PDF pages; None for raster files

@dataclass
class IngestionResult:
    kind: FileKind
    sha256: str  # of the original uploaded bytes
    pages: list[PageImage]