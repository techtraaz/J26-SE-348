from app.graph.migrate import (
    MIGRATIONS_DIR,
    all_statements,
    constraint_statements,
    file_statements,
    migrate,
    vector_index_statement,
)
from app.ontology.model import load_ontology


def test_one_unique_constraint_per_node_label():
    onto = load_ontology()
    stmts = constraint_statements(onto)
    assert len(stmts) == len(onto.nodes)
    assert any("FOR (n:CheckRule) REQUIRE n.rule_id IS UNIQUE" in s for s in stmts)
    assert any("regulatory_body_code_unique" in s for s in stmts)


def test_vector_index_uses_given_dimensions():
    stmt = vector_index_statement(384)
    assert "`vector.dimensions`: 384" in stmt
    assert stmt.endswith("}}")


def test_cypher_files_split_and_skip_comments():
    stmts = file_statements(MIGRATIONS_DIR / "001_indexes.cypher")
    assert stmts and all(s.startswith("CREATE INDEX") for s in stmts)


def test_every_statement_is_idempotent():
    assert all("IF NOT EXISTS" in s for s in all_statements(dims=768))


def test_migrate_runs_all_statements():
    ran = []
    done = migrate(lambda q, **_: ran.append(q) or [], dims=768)
    assert ran == done
