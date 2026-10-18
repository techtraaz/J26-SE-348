import argparse
from pathlib import Path

from app.construction.chunker import chunk_document
from app.construction.loaders import load_pdf
from app.construction.resolve import section_id
from app.graph import neo4j_client

RAW_DIR = Path("data/standards/raw")

# a stale section is only removed when nothing but its standard and chunks point at it
STALE_SECTIONS = """
MATCH (s:Section {source: $file}) WHERE NOT s.id IN $keep
  AND NOT EXISTS { (s)-[r]-() WHERE NOT type(r) IN ['HAS_SECTION', 'EXTRACTED_FROM'] }
RETURN s.id AS id ORDER BY id"""
STALE_CHUNKS = """
MATCH (c:SourceChunk {file: $file}) WHERE NOT c.id IN $keep
RETURN c.id AS id ORDER BY id"""

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Remove sections and chunks the chunker no longer makes (deleted paragraphs, intros)")
    ap.add_argument("files", nargs="*", help="only these PDFs (default: all in data/standards/raw)")
    ap.add_argument("--apply", action="store_true", help="delete; without it only lists")
    args = ap.parse_args()

    paths = [RAW_DIR / f for f in args.files] or sorted(RAW_DIR.glob("*.pdf"))
    total_s = total_c = 0
    try:
        for path in paths:
            chunks = chunk_document(load_pdf(path))
            keep_c = [c.id for c in chunks]
            keep_s = sorted({section_id(c.id) for c in chunks})
            sections = [r["id"] for r in neo4j_client.run_read(STALE_SECTIONS, file=path.name, keep=keep_s)]
            stale = [r["id"] for r in neo4j_client.run_read(STALE_CHUNKS, file=path.name, keep=keep_c)]
            if not sections and not stale:
                continue
            print(f"{path.name}: {len(sections)} sections, {len(stale)} chunks  e.g. {(sections or stale)[:3]}")
            total_s += len(sections)
            total_c += len(stale)
            if args.apply:
                neo4j_client.run_write("MATCH (c:SourceChunk) WHERE c.id IN $ids DETACH DELETE c", ids=stale)
                neo4j_client.run_write("MATCH (s:Section) WHERE s.id IN $ids DETACH DELETE s", ids=sections)
    finally:
        neo4j_client.close_driver()
    print(f"{'deleted' if args.apply else 'would delete'}: {total_s} sections, {total_c} chunks")
