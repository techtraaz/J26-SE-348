"""File type detection by content (magic bytes), never by extension."""

from app.services.ingestion.models import FileKind, IngestionError

def detect_kind(data: bytes) -> FileKind:
    if not data:
        raise IngestionError("empty_file", "The file is empty.")

    head = data[:16]

    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return FileKind.PNG
    if head.startswith(b"\xff\xd8\xff"):
        return FileKind.JPEG
    if head[:4] in (b"II*\x00", b"MM\x00*"):  # classic TIFF, both byte orders
        return FileKind.TIFF
    # "BM" alone is a weak signature; the BMP header's two reserved fields
    # (bytes 6-9) must also be zero.
    if head.startswith(b"BM") and len(head) >= 10 and head[6:10] == b"\x00\x00\x00\x00":
        return FileKind.BMP
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return FileKind.WEBP
    # The PDF spec allows junk before the header within the first 1024 bytes.
    if b"%PDF-" in data[:1024]:
        return FileKind.PDF

    raise IngestionError(
        "unsupported_type",
        "Unsupported file type. Supported types: PNG, JPEG, TIFF, BMP, WebP and PDF.",
    )