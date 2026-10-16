import argparse
import json
from collections import Counter
from pathlib import Path

from app.construction.context import Neo4jReader, SeedReader
from app.construction.llm import get_llm
from app.construction.loaders import load_pdf
from app.construction.pipeline import KGPipeline
from app.graph import neo4j_client

RAW_DIR = Path("data/standards/raw")
OUT_DIR = Path("data/standards/processed")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Run extraction on PDFs without writing to Neo4j")
    ap.add_argument("files", nargs="*", help="PDF names in data/standards/raw (default: all)")
    ap.add_argument("--max-chunks", type=int, default=None)
    ap.add_argument("--offline", action="store_true", help="read context from seed files")
    args = ap.parse_args()

    reader = SeedReader() if args.offline else Neo4jReader(neo4j_client.run_read)
    pipeline = KGPipeline(get_llm(), reader, max_chunks=args.max_chunks)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        for name in args.files or sorted(p.name for p in RAW_DIR.glob("*.pdf")):
            result = pipeline.run(load_pdf(RAW_DIR / name))
            issues = Counter(i.action for r in result.results for i in r.issues)
            reqs = sum(len(r.extraction.requirements) for r in result.results)
            defs = sum(len(r.extraction.definitions) for r in result.results)
            print(f"{name[:45]:<46} {result.kind:<10} chunks {result.chunks:>4} "
                  f"sent {len(result.results) + len(result.errors):>4} reqs {reqs:>4} "
                  f"defs {defs:>3} errors {len(result.errors)} issues {dict(issues)}")
            out = OUT_DIR / f"{Path(name).stem}.json"
            out.write_text(json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8")
    finally:
        neo4j_client.close_driver()
