import argparse
import json
import logging
from pathlib import Path

from app.config import get_settings
from app.construction.batch import corpus_totals, ingest_files
from app.construction.loaders import load_pdf
from app.construction.service import build_pipeline
from app.graph import neo4j_client

RAW_DIR = Path("data/standards/raw")
OUT_DIR = Path("data/standards/processed")
MANIFEST = OUT_DIR / "manifest.json"

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Ingest all standards PDFs into the KG, resumable")
    ap.add_argument("files", nargs="*", help="only these PDFs (default: all in data/standards/raw)")
    ap.add_argument("--dry-run", action="store_true", help="extract but do not write to Neo4j")
    ap.add_argument("--force", action="store_true", help="redo files already marked done")
    ap.add_argument("--max-chunks", type=int, default=None, help="limit LLM calls per file")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(OUT_DIR / "ingest.log", encoding="utf-8")])
    for noisy in ("pypdf", "neo4j", "httpx", "openai"):
        logging.getLogger(noisy).setLevel(logging.ERROR)

    s = get_settings()
    model = f"{s.llm_provider}:{s.llm_model}"
    paths = [RAW_DIR / f for f in args.files] or sorted(RAW_DIR.glob("*.pdf"))
    pipeline = build_pipeline(write=not args.dry_run, max_chunks=args.max_chunks)
    try:
        out = ingest_files(paths, pipeline, load_pdf, MANIFEST, model, OUT_DIR, args.force)
    finally:
        neo4j_client.close_driver()

    totals = corpus_totals(out["manifest"])
    (OUT_DIR / "summary.json").write_text(json.dumps(totals, indent=2), encoding="utf-8")
    print(f"\nthis run: {out['totals']}")
    print(f"corpus:   {totals}")
