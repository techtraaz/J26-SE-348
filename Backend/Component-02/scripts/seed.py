import sys
from pathlib import Path

from app.config import get_settings
from app.graph import neo4j_client
from app.ontology.model import load_ontology
from app.ontology.seed import load_seed, validate, write

RAW_DIR = Path("data/standards/raw")

if __name__ == "__main__":
    onto = load_ontology()
    seed = load_seed()
    errors = validate(seed, onto)
    if errors:
        print(f"{len(errors)} seed errors:")
        for e in errors:
            print("  " + e)
        sys.exit(1)

    missing = [s["file"] for s in seed.nodes.get("Standard", [])
               if s.get("file") and not (RAW_DIR / s["file"]).exists()]
    if missing:
        print("warning: PDFs not found in data/standards/raw:", ", ".join(missing))

    nodes = sum(len(v) for v in seed.nodes.values())
    print(f"Seed OK: {nodes} nodes, {len(seed.rels)} relationships from {', '.join(seed.files)}")
    if "--check" in sys.argv:
        sys.exit(0)

    print(f"Writing to {get_settings().neo4j_uri}")
    try:
        for name, count in write(seed, onto, neo4j_client.run_write).items():
            print(f"  {name:<20} {count}")
    finally:
        neo4j_client.close_driver()
