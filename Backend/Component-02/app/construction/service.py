from app.config import get_settings
from app.construction.context import Neo4jReader
from app.construction.llm import get_llm
from app.construction.pipeline import KGPipeline
from app.graph import neo4j_client


def build_pipeline(write: bool = True, max_chunks: int | None = None,
                   workers: int | None = None, embed: bool = True) -> KGPipeline:
    """Pipeline wired to the configured LLM and Neo4j."""
    s = get_settings()
    return KGPipeline(
        get_llm(), Neo4jReader(neo4j_client.run_read),
        run_write=neo4j_client.run_write if write else None, max_chunks=max_chunks,
        embed=embed and s.llm_provider != "fake", workers=workers or s.llm_workers)


def graph_totals() -> dict:
    nodes = neo4j_client.run_read("MATCH (n) RETURN count(n) AS n")[0]["n"]
    rels = neo4j_client.run_read("MATCH ()-[r]->() RETURN count(r) AS n")[0]["n"]
    return {"nodes": nodes, "relationships": rels}
