"""Run any supported file (image, TIFF, PDF) through ingestion + an OCR engine.

Run from the backend folder:
    uv run python scripts/smoke_ocr.py [file] [--dpi N] [--repeat N]
        [--unwarp] [--no-doc-orientation] [--mkldnn]
        [--det-model NAME] [--rec-model NAME]
        [--engine replay [--fixture PATH] [--delay SECONDS]]

Defaults to data/samples/sample_invoice.png with the real PaddleOCR engine.
Output (JSON + the OCR-space image of every page) goes to data/results/.
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
from app.services.ingestion.models import DEFAULT_PDF_DPI, IngestionError  # noqa: E402
from app.services.ingestion.pipeline import ingest  # noqa: E402
from app.services.factory import create_engine  # noqa: E402
from app.services.ocr.paddle import PaddleSettings  # noqa: E402

def save_png(path: Path, image: np.ndarray) -> None:
    # imencode + tofile instead of cv2.imwrite: imwrite fails on non-ASCII
    # Windows paths.
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValueError(f"Could not encode image for {path}")
    buf.tofile(str(path))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "file",
        nargs="?",
        type=Path,
        default=BACKEND_ROOT / "data" / "samples" / "sample_invoice.png",
    )
    parser.add_argument("--dpi", type=int, default=DEFAULT_PDF_DPI, help="PDF rasterization DPI")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--max-pages", type=int, default=None, help="only process the first N pages")
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

    try:
        ingested = ingest(args.file.read_bytes(), pdf_dpi=args.dpi)
    except IngestionError as err:
        sys.exit(f"Ingestion failed [{err.code}]: {err.message}")

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

    info = engine.info()
    shown = {k: v for k, v in info.settings.items() if k != "runtime"}
    print(f"\nFile: {args.file.name} | {ingested.kind.value} | {len(ingested.pages)} page(s) "
          f"| sha256 {ingested.sha256[:12]}")
    print(f"Engine: {info.name} | settings: {shown}")

    tags = [
        t
        for t, on in (
            ("unwarp", args.unwarp),
            ("no-doc-orient", args.no_doc_orientation),
            ("mkldnn", args.mkldnn),
            (f"det-{args.det_model}", args.det_model is not None),
            (f"rec-{args.rec_model}", args.rec_model is not None),
        )
        if on
    ]
    label = "replay" if args.engine == "replay" else ("-".join(tags) or "default")
    name = f"{args.file.stem}.{label}"
    out_dir = BACKEND_ROOT / "data" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)

    page_results = []
    for page_image in ingested.pages:
        h, w = page_image.image.shape[:2]
        dpi_note = f", {page_image.dpi} DPI" if page_image.dpi else ""
        for run in range(1, args.repeat + 1):
            recognition = engine.recognize_page(page_image.image, page_image.page_number)
            print(
                f"Page {page_image.page_number} ({w}x{h}px{dpi_note}) run {run}: "
                f"{recognition.page.elapsed_ms:.0f} ms, {len(recognition.page.lines)} lines"
            )
        page_results.append(recognition.page)
        save_png(out_dir / f"{name}.p{page_image.page_number}.ocr.png", recognition.ocr_image)

    result = ExtractionResult(engine=info, pages=page_results)
    (out_dir / f"{name}.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(f"\nSaved to: {out_dir} ({name}.json + one .ocr.png per page)")

    first = page_results[0]
    print("\nFirst page, first 3 lines:")
    for line in first.lines[:3]:
        print(f"  {line.confidence:.4f}  {line.box}  {line.text!r}")
    print("\nFirst page, 5 lowest-confidence lines:")
    for line in sorted(first.lines, key=lambda ln: ln.confidence)[:5]:
        print(f"  {line.confidence:.4f}  {line.text!r}")


if __name__ == "__main__":
    main()