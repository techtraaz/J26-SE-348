"""Engine-agnostic extraction schema."""
from pydantic import BaseModel

class OCRLine(BaseModel):
    text: str
    # Raw engine-reported score, passed through untouched (no clamping, no thresholding).
    confidence: float
    box: tuple[int, int, int, int]  # axis-aligned: x1, y1, x2, y2 (pixels)
    polygon: list[tuple[int, int]]  # 4 corner points (pixels)

class PageResult(BaseModel):
    page_number: int  # 1-based
    width: int
    height: int
    lines: list[OCRLine]
    elapsed_ms: float  # per-page latency; needed for the efficiency comparison

class EngineInfo(BaseModel):
    name: str
    version: str
    settings: dict[str, object]  # exact settings used, recorded with every run

class ExtractionResult(BaseModel):
    engine: EngineInfo
    pages: list[PageResult]