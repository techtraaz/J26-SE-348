"""PaddleOCR 3.x engine wrapper.

Two design points:
- The CPU workaround flags and the `paddleocr` import both happen inside
  PaddleOCREngine.__init__, so the flags are guaranteed to be set before
  paddle is imported, no matter what the rest of the app imports first.
- lines_from_result() is a pure function with no paddle dependency, so the
  raw-result -> schema conversion can be unit-tested without loading models.
"""

import os
import platform
import time
from dataclasses import dataclass
from importlib.metadata import version

import numpy as np

from app.schemas.extraction import EngineInfo, OCRLine, PageResult
from app.services.ocr.base import OCREngine, PageRecognition

# Workarounds for oneDNN / PIR errors with Paddle 3.x on Windows CPU.
# setdefault so an explicit value in the environment still wins.
def cpu_flags(settings: "PaddleSettings") -> dict[str, str]:
    return {
        "FLAGS_use_mkldnn": "1" if settings.enable_mkldnn else "0",
        "FLAGS_enable_pir_api": "0",
        "FLAGS_enable_pir_in_executor": "0",
    }


@dataclass(frozen=True)
class PaddleSettings:
    lang: str = "en"
    use_doc_orientation_classify: bool = True
    # Off by default: on a flat, clean scan UVDoc unwarping distorted/cropped
    # the page and changed line segmentation (measured, see plan §2). Kept as
    # a per-run experimental variable for curved / photographed documents.
    use_doc_unwarping: bool = False
    use_textline_orientation: bool = True
    enable_mkldnn: bool = False
    # None = PaddleOCR default models for `lang`.
    text_detection_model_name: str | None = None
    text_recognition_model_name: str | None = None


def build_paddle_kwargs(settings: PaddleSettings) -> dict:
    """Exactly the keyword arguments passed to PaddleOCR(...).

    Recorded with every run, so what is stored is what was applied.
    Note: passing engine/engine_config (PaddleOCR 3.5+) crashed on this
    machine with a oneDNN/PIR error, so it is deliberately not used.
    """
    kwargs: dict = {
        "lang": settings.lang,
        "use_doc_orientation_classify": settings.use_doc_orientation_classify,
        "use_doc_unwarping": settings.use_doc_unwarping,
        "use_textline_orientation": settings.use_textline_orientation,
        "enable_mkldnn": settings.enable_mkldnn,
    }
    if settings.text_detection_model_name:
        kwargs["text_detection_model_name"] = settings.text_detection_model_name
    if settings.text_recognition_model_name:
        kwargs["text_recognition_model_name"] = settings.text_recognition_model_name
    return kwargs


def runtime_info() -> dict:
    """Hardware/software context; latency numbers are only comparable per machine."""
    return {
        "platform": platform.platform(),
        "processor": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "python": platform.python_version(),
    }


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


def ocr_image_from_result(res, fallback: np.ndarray) -> np.ndarray:
    """Return the image the result's coordinates refer to.

    With document preprocessing enabled (orientation / unwarping), Paddle
    detects text on its own preprocessed image, stored at
    res["doc_preprocessor_res"]["output_img"]. Boxes align with THAT image,
    not necessarily with the input. If the key is absent, fall back to the
    input image.
    """
    pre = res.get("doc_preprocessor_res")
    if pre is not None:
        out = pre.get("output_img")
        if out is not None:
            return np.asarray(out)
    return fallback


class PaddleOCREngine(OCREngine):
    def __init__(self, settings: PaddleSettings | None = None) -> None:
        self._settings = settings or PaddleSettings()

        flags = cpu_flags(self._settings)
        for key, value in flags.items():
            os.environ.setdefault(key, value)

        # Imported here on purpose: flags above must be set first.
        from paddleocr import PaddleOCR

        self._kwargs = build_paddle_kwargs(self._settings)
        self._ocr = PaddleOCR(**self._kwargs)
        self._version = version("paddleocr")

    def info(self) -> EngineInfo:
        return EngineInfo(
            name="paddleocr",
            version=self._version,
            settings={
                **self._kwargs,
                "env_flags": {k: os.environ.get(k) for k in cpu_flags(self._settings)},
                "runtime": runtime_info(),
            },
        )

    def recognize_page(self, image: np.ndarray, page_number: int = 1) -> PageRecognition:
        start = time.perf_counter()
        results = list(self._ocr.predict(image))
        elapsed_ms = (time.perf_counter() - start) * 1000

        lines: list[OCRLine] = []
        for res in results:
            lines.extend(lines_from_result(res))

        # One image in -> one result out. Coordinates live in the OCR-space image.
        ocr_image = ocr_image_from_result(results[0], image) if results else image
        height, width = ocr_image.shape[:2]

        page = PageResult(
            page_number=page_number,
            width=width,
            height=height,
            lines=lines,
            elapsed_ms=elapsed_ms,
        )
        return PageRecognition(page=page, ocr_image=ocr_image)