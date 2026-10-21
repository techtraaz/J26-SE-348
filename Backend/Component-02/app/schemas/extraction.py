from pydantic import BaseModel


# same shape as Component 01 app/schemas/extraction.py
class OCRLine(BaseModel):
    text: str
    confidence: float
    box: tuple[int, int, int, int]
    polygon: list[tuple[int, int]]


class PageResult(BaseModel):
    page_number: int
    width: int
    height: int
    lines: list[OCRLine]
    elapsed_ms: float


class EngineInfo(BaseModel):
    name: str
    version: str
    settings: dict[str, object]


class ExtractionResult(BaseModel):
    engine: EngineInfo
    pages: list[PageResult]
