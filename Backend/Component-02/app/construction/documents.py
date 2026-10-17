from dataclasses import dataclass, field


@dataclass
class Page:
    number: int
    text: str
    confidence: float | None = None  # mean OCR confidence, None for text PDFs


@dataclass
class LoadedDocument:
    file: str
    code: str | None  # standard code such as "LKAS 2", None if not a standard
    source: str  # "pdf" or "ocr"
    pages: list[Page] = field(default_factory=list)


@dataclass
class Chunk:
    id: str
    file: str
    page: int
    text: str
    number: str | None = None  # paragraph number, e.g. "54", "81A", "QC11"
    heading: str | None = None
    confidence: float | None = None
