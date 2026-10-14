"""Standalone OCR smoke test through the engine + normalized schema."""

import sys
from pathlib import Path

# Make `app` importable when running this file directly.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import cv2  # noqa: E402  (installed as a PaddleOCR dependency)
import numpy as np  # noqa: E402

from app.schemas.extraction import ExtractionResult  # noqa: E402
from app.services.ocr.paddle import PaddleOCREngine  # noqa: E402


def load_image(path: Path) -> np.ndarray:
    # np.fromfile + imdecode instead of cv2.imread: imread fails on
    # non-ASCII Windows paths.
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not decode image: {path}")
    return image


def main() -> None:
    image_path = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else BACKEND_ROOT / "data" / "samples" / "sample_invoice.png"
    )

    engine = PaddleOCREngine()
    page = engine.recognize_page(load_image(image_path), page_number=1)
    result = ExtractionResult(engine=engine.info(), pages=[page])

    # Full result saved to disk; terminal gets a short summary only.
    out_dir = BACKEND_ROOT / "data" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{image_path.stem}.json"
    out_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    print(f"{len(page.lines)} lines | {page.width}x{page.height}px | {page.elapsed_ms:.0f} ms")
    print(f"Full result saved to: {out_path}\n")

    print("First 3 lines:")
    for line in page.lines[:3]:
        print(f"  {line.confidence:.4f}  {line.box}  {line.text!r}")

    print("\n5 lowest-confidence lines:")
    for line in sorted(page.lines, key=lambda ln: ln.confidence)[:5]:
        print(f"  {line.confidence:.4f}  {line.text!r}")


if __name__ == "__main__":
    main()