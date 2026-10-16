from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from neo4j.exceptions import Neo4jError

from app.api import query as query_api
from app.main import app
from app.query import cypher
from app.query.cypher import CypherRejected, _clean, check_query

client = TestClient(app)


@pytest.mark.parametrize("text", [
    "MATCH (s:Standard) RETURN s.code",
    "MATCH (n) WHERE n.text CONTAINS 'set' RETURN count(n)",
    "MATCH (n) WHERE n.note = \"DELETE me\" RETURN n // CREATE in a comment",
    "MATCH (e:Event) RETURN e.start, e.set_by",
    "CALL db.index.fulltext.queryNodes('regulatory_text', 'going concern') YIELD node RETURN node",
    "MATCH (n) RETURN n;",
])
def test_reads_are_allowed(text):
    check_query(text)


@pytest.mark.parametrize("text,reason", [
    ("MATCH (n) DETACH DELETE n", "DETACH"),
    ("CREATE (:X)", "CREATE"),
    ("MATCH (n) SET n.x = 1", "SET"),
    ("MERGE (n:X {id: 1})", "MERGE"),
    ("LOAD CSV FROM 'file:///x' AS row RETURN row", "LOAD"),
    ("CALL dbms.components()", "CALL dbms.components"),
    ("CALL apoc.periodic.iterate('x','y',{})", "CALL apoc.periodic.iterate"),
    ("CALL { MATCH (n) RETURN n } RETURN 1", "CALL {...}"),
    ("MATCH (n) RETURN n; MATCH (m) DETACH DELETE m", "one statement"),
])
def test_writes_and_admin_calls_are_rejected(text, reason):
    with pytest.raises(CypherRejected, match=reason.replace("(", r"\(").replace("{", r"\{")):
        check_query(text)


def test_embeddings_are_hidden_from_results():
    row = {"c": {"id": "LKAS 2:9", "embedding": [0.1] * 768, "nested": [{"embedding": [1]}]}}
    assert _clean(row) == {"c": {"id": "LKAS 2:9", "nested": [{}]}}


def _error(code, message):
    return Neo4jError._hydrate_neo4j(code=code, message=message)


@pytest.mark.parametrize("exc,status", [
    (CypherRejected("Read-only endpoint: 'CREATE' is not allowed"), 400),
    (_error("Neo.ClientError.Statement.SyntaxError", "Invalid input"), 400),
    (_error("Neo.ClientError.Security.Forbidden", "Writing in read access mode"), 403),
    (_error("Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration", "timed out"), 408),
])
def test_errors_map_to_http_status(monkeypatch, exc, status):
    def boom(*_a, **_k):
        raise exc
    monkeypatch.setattr(cypher, "run_checked", boom)
    assert client.post("/query/cypher", json={"query": "MATCH (n) RETURN n"}).status_code == status


def test_parameters_are_passed_through(monkeypatch):
    seen = []
    monkeypatch.setattr(cypher, "run_checked", lambda q, p: seen.append((q, p)) or {"rows": []})
    client.post("/query/cypher", json={"query": "MATCH (s:Standard {code: $c}) RETURN s",
                                       "params": {"c": "LKAS 2"}})
    assert seen == [("MATCH (s:Standard {code: $c}) RETURN s", {"c": "LKAS 2"})]


def test_endpoint_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(query_api, "get_settings",
                        lambda: SimpleNamespace(query_cypher_enabled=False))
    assert client.post("/query/cypher", json={"query": "MATCH (n) RETURN n"}).status_code == 403


def test_empty_query_is_rejected():
    assert client.post("/query/cypher", json={"query": ""}).status_code == 422
