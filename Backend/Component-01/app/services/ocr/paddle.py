"""PaddleOCR 3.x engine wrapper."""

import os
import time
from dataclasses import asdict, dataclass
from importlib.metadata import version

import numpy as np

from app.schemas.extraction import EngineInfo, OCRLine, PageResult
from app.services.ocr.base import OCREngine

# Workarounds for oneDNN / PIR errors with Paddle 3.x on Windows CPU.
_CPU_FLAGS = {
    "FLAGS_use_mkldnn": "0",
    "FLAGS_enable_pir_api": "0",
    "FLAGS_enable_pir_in_executor": "0",
}


@dataclass(frozen=True)
class PaddleSettings:
    """Keys must match PaddleOCR constructor argument names."""

    lang: str = "en"
    use_doc_orientation_classify: bool = True
    use_doc_unwarping: bool = True
    use_textline_orientation: bool = True
    enable_mkldnn: bool = False


def lines_from_result(res) -> list[OCRLine]:
    """Convert one raw PaddleOCR result into plain-Python OCRLine objects.

    rec_texts / rec_scores / rec_boxes / rec_polys are parallel arrays
    (same index = same text line). Values are numpy types, so every one
    is converted to a built-in int/float/str here.
    """
    texts = res.get("rec_texts", [])
    scores = res.get("rec_scores", [])
    boxes = res.get("rec_boxes", [])
    polys = res.get("rec_polys", [])

    if not (len(texts) == len(scores) == len(boxes) == len(polys)):
        raise ValueError(
            "PaddleOCR result arrays differ in length: "
            f"texts={len(texts)}, scores={len(scores)}, "
            f"boxes={len(boxes)}, polys={len(polys)}"
        )

    return [
        OCRLine(
            text=str(text),
            confidence=float(score),
            box=tuple(int(v) for v in box),
            polygon=[(int(x), int(y)) for x, y in poly],
        )
        for text, score, box, poly in zip(texts, scores, boxes, polys)
    ]


class PaddleOCREngine(OCREngine):
    def __init__(self, settings: PaddleSettings | None = None) -> None:
        self._settings = settings or PaddleSettings()

        for key, value in _CPU_FLAGS.items():
            os.environ.setdefault(key, value)

        from paddleocr import PaddleOCR

        self._ocr = PaddleOCR(**asdict(self._settings))
        self._version = version("paddleocr")

    def info(self) -> EngineInfo:
        return EngineInfo(
            name="paddleocr",
            version=self._version,
            settings=asdict(self._settings),
        )

    def recognize_page(self, image: np.ndarray, page_number: int = 1) -> PageResult:
        start = time.perf_counter()
        results = self._ocr.predict(image)
        elapsed_ms = (time.perf_counter() - start) * 1000

        lines: list[OCRLine] = []
        for res in results:
            lines.extend(lines_from_result(res))

        height, width = image.shape[:2]
        return PageResult(
            page_number=page_number,
            width=width,
            height=height,
            lines=lines,
            elapsed_ms=elapsed_ms,
        )