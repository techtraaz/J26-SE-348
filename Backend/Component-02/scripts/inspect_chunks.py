import sys
from collections import Counter
from pathlib import Path

from app.construction.chunker import chunk_document
from app.construction.loaders import load_pdf

RAW_DIR = Path("data/standards/raw")

if __name__ == "__main__":
    names = sys.argv[1:] or sorted(p.name for p in RAW_DIR.glob("*.pdf"))
    show = len(sys.argv) == 2
    for name in names:
        doc = load_pdf(RAW_DIR / name)
        chunks = chunk_document(doc)
        dups = sum(1 for c in chunks if "#dup" in c.id)
        sizes = [len(c.text) for c in chunks]
        print(f"{name[:48]:<49} {len(doc.pages):>4}p {len(chunks):>5} chunks "
              f"max {max(sizes):>5}c  dups {dups}")
        if show:
            for c in chunks:
                print(f"  [{c.id}] p{c.page} | {c.heading} | {c.text[:90]!r}")
            print(Counter(c.heading for c in chunks).most_common(5))
