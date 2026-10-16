"""Replay engine: serves a saved extraction result instead of running OCR.
For APP DEVELOPMENT ONLY (ingestion, API, review UI, job status).
"""

import time
from pathlib import Path

import numpy as np

from app.schemas.extraction import EngineInfo, ExtractionResult, OCRLine, PageResult
from app.services.ocr.base import OCREngine, PageRecognition


def rescale_page(page: PageResult, width: int, height: int, page_number: int) -> PageResult:
    """Copy `page` with coordinates scaled to a width x height image.

    Keeps boxes inside the image when the replayed fixture was recorded at a
    different size (e.g. a PDF page rasterized at another DPI). The boxes only
    sit on real text when the input is the document the fixture came from.
    """
    sx = width / page.width
    sy = height / page.height

    def sc(x: int, y: int) -> tuple[int, int]:
        return round(x * sx), round(y * sy)

    lines = []
    for line in page.lines:
        x1, y1 = sc(line.box[0], line.box[1])
        x2, y2 = sc(line.box[2], line.box[3])
        lines.append(
            OCRLine(
                text=line.text,
                confidence=line.confidence,
                box=(x1, y1, x2, y2),
                polygon=[sc(x, y) for x, y in line.polygon],
            )
        )
    return PageResult(
        page_number=page_number,
        width=width,
        height=height,
        lines=lines,
        elapsed_ms=page.elapsed_ms,
    )


class ReplayEngine(OCREngine):
    def __init__(self, fixture_path: Path | str, simulate_delay_s: float = 0.0) -> None:
        self._fixture_path = Path(fixture_path)
        fixture = ExtractionResult.model_validate_json(
            self._fixture_path.read_text(encoding="utf-8")
        )
        if not fixture.pages:
            raise ValueError(f"Fixture has no pages: {self._fixture_path}")
        self._fixture = fixture
        # Lets the UI exercise its "processing" state without real OCR.
        self._delay = simulate_delay_s

    def info(self) -> EngineInfo:
        return EngineInfo(
            name="replay",
            version="1",
            settings={
                "fixture": self._fixture_path.name,
                "simulate_delay_s": self._delay,
                "replayed_from": self._fixture.engine.model_dump(),
            },
        )

    def recognize_page(self, image: np.ndarray, page_number: int = 1) -> PageRecognition:
        start = time.perf_counter()
        if self._delay > 0:
            time.sleep(self._delay)

        height, width = image.shape[:2]
        page = rescale_page(self._fixture.pages[0], width, height, page_number)
        page = page.model_copy(update={"elapsed_ms": (time.perf_counter() - start) * 1000})

        # No preprocessing happens here, so the OCR-space image is the input.
        return PageRecognition(page=page, ocr_image=image)