import argparse
import sys
import time

from app.config import get_settings
from app.construction.llm import get_llm
from app.graph import neo4j_client
from app.graph.migrate import vector_index_statement

INDEX = "source_chunk_embedding"
NEXT = """MATCH (c:SourceChunk) WHERE c.embedding IS NULL AND c.text IS NOT NULL
RETURN c.id AS id, c.text AS text ORDER BY id LIMIT $n"""
SAVE = """UNWIND $rows AS r MATCH (c:SourceChunk {id: r.id}) SET c.embedding = r.vector"""


def index_dims() -> int | None:
    rows = neo4j_client.run_read(
        "SHOW VECTOR INDEXES YIELD name, options WHERE name = $name "
        "RETURN options.indexConfig['vector.dimensions'] AS dims", name=INDEX)
    return rows[0]["dims"] if rows else None


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Embed SourceChunks that have no embedding (resumable, no chat LLM needed)")
    ap.add_argument("--all", action="store_true", help="clear and redo every embedding")
    ap.add_argument("--recreate-index", action="store_true",
                    help="drop and recreate the vector index with EMBEDDING_DIM (after a model change)")
    ap.add_argument("--batch", type=int, default=32)
    args = ap.parse_args()

    s = get_settings()
    if s.llm_provider == "fake":
        sys.exit("LLM_PROVIDER=fake gives fake vectors; set a real embedding server first")
    llm = get_llm()
    try:
        dims = index_dims()
        if args.recreate_index:
            neo4j_client.run_write(f"DROP INDEX {INDEX} IF EXISTS")
            neo4j_client.run_write(vector_index_statement(s.embedding_dim))
            args.all = True
        elif dims != s.embedding_dim:
            sys.exit(f"vector index has {dims} dimensions, EMBEDDING_DIM={s.embedding_dim}; "
                     "run with --recreate-index")
        if args.all:
            neo4j_client.run_write("MATCH (c:SourceChunk) SET c.embedding = null")

        todo = neo4j_client.run_read("MATCH (c:SourceChunk) WHERE c.embedding IS NULL RETURN count(c) AS n")[0]["n"]
        print(f"{todo} chunks to embed with {s.embedding_model} ({s.embedding_dim} dims)")
        done, start = 0, time.time()
        while rows := neo4j_client.run_read(NEXT, n=args.batch):
            vectors = llm.embed([r["text"] for r in rows])
            neo4j_client.run_write(SAVE, rows=[{"id": r["id"], "vector": v}
                                               for r, v in zip(rows, vectors, strict=True)])
            done += len(rows)
            if done % (args.batch * 10) < args.batch or done == todo:
                print(f"  {done}/{todo}  {time.time() - start:.0f}s", flush=True)
    finally:
        neo4j_client.close_driver()
    print("done")
