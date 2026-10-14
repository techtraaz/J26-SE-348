"""Standalone OCR smoke test / latency probe through the engine + schema.

Run from the backend folder:
    uv run python scripts/smoke_ocr.py [image] [--repeat N]
                                       [--unwarp] [--no-doc-orientation] [--mkldnn]
                                       [--det-model NAME] [--rec-model NAME]
                                       [--engine replay [--fixture PATH] [--delay SECONDS]]

Defaults to data/samples/sample_invoice.png, 2 runs in one process so the
first (warm-up) timing can be separated from steady-state timing.
"""

import argparse
import sys
from pathlib import Path

# Make `app` importable when running this file directly.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import cv2  # noqa: E402  (installed as a PaddleOCR dependency)
import numpy as np  # noqa: E402

from app.schemas.extraction import ExtractionResult  # noqa: E402
from app.services.ocr.factory import create_engine  # noqa: E402
from app.services.ocr.paddle import PaddleSettings  # noqa: E402


def load_image(path: Path) -> np.ndarray:
    # np.fromfile + imdecode instead of cv2.imread: imread fails on
    # non-ASCII Windows paths.
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not decode image: {path}")
    return image


def save_png(path: Path, image: np.ndarray) -> None:
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValueError(f"Could not encode image for {path}")
    buf.tofile(str(path))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "image",
        nargs="?",
        type=Path,
        default=BACKEND_ROOT / "data" / "samples" / "sample_invoice.png",
    )
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--unwarp", action="store_true")
    parser.add_argument("--no-doc-orientation", action="store_true")
    parser.add_argument("--mkldnn", action="store_true")
    parser.add_argument("--det-model", default=None)
    parser.add_argument("--rec-model", default=None)
    parser.add_argument("--engine", choices=["paddle", "replay"], default="paddle")
    parser.add_argument(
        "--fixture",
        type=Path,
        default=BACKEND_ROOT / "tests" / "fixtures" / "sample_invoice.default.json",
    )
    parser.add_argument("--delay", type=float, default=0.0)
    args = parser.parse_args()

    settings = PaddleSettings(
        use_doc_unwarping=args.unwarp,
        use_doc_orientation_classify=not args.no_doc_orientation,
        enable_mkldnn=args.mkldnn,
        text_detection_model_name=args.det_model,
        text_recognition_model_name=args.rec_model,
    )
    engine = create_engine(
        args.engine,
        settings=settings,
        fixture=args.fixture,
        simulate_delay_s=args.delay,
    )
    image = load_image(args.image)

    info_settings = engine.info().settings
    print(f"\nEngine: {engine.info().name} | settings: { {k: v for k, v in info_settings.items() if k not in ('runtime',)} }")
    print(f"Input image: {image.shape[1]}x{image.shape[0]}px")

    recognition = None
    for i in range(1, args.repeat + 1):
        recognition = engine.recognize_page(image, page_number=1)
        page = recognition.page
        label = "warm-up" if i == 1 else "steady"
        print(f"Run {i} ({label}): {page.elapsed_ms:.0f} ms, {len(page.lines)} lines")

    page = recognition.page
    result = ExtractionResult(engine=engine.info(), pages=[page])

    # Full result + the OCR-space image saved to disk; terminal gets a summary.
    out_dir = BACKEND_ROOT / "data" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    tags = [t for t, on in (
            ("unwarp", args.unwarp),
            ("no-doc-orient", args.no_doc_orientation),
            ("mkldnn", args.mkldnn),
            (f"det-{args.det_model}", args.det_model is not None),
            (f"rec-{args.rec_model}", args.rec_model is not None),
        ) if on]
    label = "replay" if args.engine == "replay" else ("-".join(tags) or "default")
    name = f"{args.image.stem}.{label}"
    (out_dir / f"{name}.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    save_png(out_dir / f"{name}.ocr.png", recognition.ocr_image)

    same_size = recognition.ocr_image.shape[:2] == image.shape[:2]
    print(
        f"OCR-space image: {page.width}x{page.height}px "
        f"({'same size as input' if same_size else 'DIFFERENT from input'})"
    )
    print(f"Saved to: {out_dir}\n")

    print("First 3 lines:")
    for line in page.lines[:3]:
        print(f"  {line.confidence:.4f}  {line.box}  {line.text!r}")

    print("\n5 lowest-confidence lines:")
    for line in sorted(page.lines, key=lambda ln: ln.confidence)[:5]:
        print(f"  {line.confidence:.4f}  {line.text!r}")


if __name__ == "__main__":
    main()