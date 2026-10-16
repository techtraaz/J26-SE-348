from app.config import get_settings
from app.construction.context import Neo4jReader
from app.construction.llm import get_llm
from app.construction.pipeline import KGPipeline
from app.graph import neo4j_client


def build_pipeline(write: bool = True, max_chunks: int | None = None) -> KGPipeline:
    """Pipeline wired to the configured LLM and Neo4j."""
    real_llm = get_settings().llm_provider != "fake"
    return KGPipeline(
        get_llm(), Neo4jReader(neo4j_client.run_read),
        run_write=neo4j_client.run_write if write else None,
        max_chunks=max_chunks, embed=real_llm)
