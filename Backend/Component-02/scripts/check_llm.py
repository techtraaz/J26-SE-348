from pathlib import Path

from app.config import get_settings
from app.construction.chunker import chunk_document
from app.construction.documents import Chunk
from app.construction.llm import get_llm
from app.construction.loaders import load_pdf
from app.construction.prompts import SYSTEM, build_user_prompt
from app.construction.schema import ChunkExtraction, ExtractionContext

SAMPLE = Path("data/standards/raw/LKAS_02_Inventories.pdf")

if __name__ == "__main__":
    s = get_settings()
    print(f"provider={s.llm_provider} model={s.llm_model} url={s.llm_base_url}")
    if SAMPLE.exists():
        chunk = next(c for c in chunk_document(load_pdf(SAMPLE)) if c.id == "LKAS 2:9")
    else:
        chunk = Chunk(id="LKAS 2:9", file="sample", page=1, number="9",
                      heading="Measurement of inventories",
                      text="9  Inventories shall be measured at the lower of cost and net realisable value.")
    ctx = ExtractionContext(line_items=["inventories", "inventory_cost", "inventory_nrv"],
                            account_classes=["CURRENT_ASSET"], document_types=["balance_sheet"])
    llm = get_llm()
    result = llm.extract(SYSTEM, build_user_prompt(chunk, "LKAS 2", ctx), ChunkExtraction)
    print(result.model_dump_json(indent=2))
    vector = llm.embed([chunk.text])[0]
    print(f"embedding size {len(vector)} (EMBEDDING_DIM={s.embedding_dim})")
