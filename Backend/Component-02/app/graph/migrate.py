import re
from collections.abc import Callable
from pathlib import Path

from app.config import get_settings
from app.ontology.model import Ontology, load_ontology

MIGRATIONS_DIR = Path(__file__).with_name("migrations")

Runner = Callable[..., list[dict]]


def _snake(label: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", label).lower()


def constraint_statements(onto: Ontology) -> list[str]:
    return [
        f"CREATE CONSTRAINT {_snake(label)}_{node.key}_unique IF NOT EXISTS "
        f"FOR (n:{label}) REQUIRE n.{node.key} IS UNIQUE"
        for label, node in onto.nodes.items()
    ]


def vector_index_statement(dims: int) -> str:
    return (
        "CREATE VECTOR INDEX source_chunk_embedding IF NOT EXISTS "
        "FOR (c:SourceChunk) ON c.embedding "
        f"OPTIONS {{indexConfig: {{`vector.dimensions`: {dims}, "
        f"`vector.similarity_function`: 'cosine'}}}}"
    )


def file_statements(path: Path) -> list[str]:
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines()
             if not ln.strip().startswith("//")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def all_statements(onto: Ontology | None = None, dims: int | None = None) -> list[str]:
    onto = onto or load_ontology()
    dims = dims or get_settings().embedding_dim
    statements = constraint_statements(onto)
    for path in sorted(MIGRATIONS_DIR.glob("*.cypher")):
        statements += file_statements(path)
    statements.append(vector_index_statement(dims))
    return statements


# every statement uses IF NOT EXISTS, so running again is safe
def migrate(run: Runner, onto: Ontology | None = None, dims: int | None = None) -> list[str]:
    statements = all_statements(onto, dims)
    for stmt in statements:
        run(stmt)
    return statements
