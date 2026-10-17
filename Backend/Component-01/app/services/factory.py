"""Single place that decides which engine implementation to build.

The API layer and scripts call create_engine(); nothing else imports a
concrete engine.
"""

from pathlib import Path

from app.services.ocr.base import OCREngine
from app.services.ocr.paddle import PaddleSettings

def create_engine(
    kind: str,
    *,
    settings: PaddleSettings | None = None,
    fixture: Path | str | None = None,
    simulate_delay_s: float = 0.0,
) -> OCREngine:
    if kind == "paddle":
        from app.services.ocr.paddle import PaddleOCREngine

        return PaddleOCREngine(settings)

    if kind == "replay":
        if fixture is None:
            raise ValueError("The replay engine needs a fixture path.")
        from app.services.replay import ReplayEngine

        return ReplayEngine(fixture, simulate_delay_s)

    raise ValueError(f"Unknown OCR engine: {kind!r}")