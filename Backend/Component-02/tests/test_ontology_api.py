from pathlib import Path

from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable

from app.graph import neo4j_client
from app.main import app
from app.ontology.model import load_ontology
from scripts.export_ontology import render

client = TestClient(app)


def test_get_ontology_lists_all_node_types():
    body = client.get("/ontology").json()
    assert len(body["nodes"]) == len(load_ontology().nodes)
    assert "Standard" in body["layers"]["regulatory"]["nodes"]
    assert body["relationships"]["BELONGS_TO"] == {"from": ["Standard"], "to": ["Framework"],
                                                   "properties": {}}


def test_get_node_type():
    body = client.get("/ontology/nodes/CheckRule").json()
    assert body["key"] == "rule_id"
    assert "IMPLEMENTS" in body["outgoing"]


def test_unknown_node_type_is_404():
    assert client.get("/ontology/nodes/Nope").status_code == 404


def test_diagram_overview_and_layer():
    overview = client.get("/ontology/diagram").text
    assert overview.startswith("flowchart LR") and "regulatory" in overview
    layer = client.get("/ontology/diagram", params={"layer": "audit"}).text
    assert "CheckRule -->|TESTS| AuditAssertion" in layer
    assert client.get("/ontology/diagram", params={"layer": "nope"}).status_code == 404


def test_stats_from_graph(monkeypatch):
    rows = iter([[{"label": "Standard", "count": 53}], [{"type": "BELONGS_TO", "count": 53}]])
    monkeypatch.setattr(neo4j_client, "run_read", lambda *_a, **_k: next(rows))
    body = client.get("/ontology/stats").json()
    assert body["total_nodes"] == 53 and body["relationships"]["BELONGS_TO"] == 53


def test_stats_when_neo4j_down(monkeypatch):
    def down(*_a, **_k):
        raise ServiceUnavailable("down")
    monkeypatch.setattr(neo4j_client, "run_read", down)
    assert client.get("/ontology/stats").status_code == 503


def test_docs_schema_section_is_up_to_date():
    doc = Path(__file__).parents[1] / "docs" / "ontology.md"
    text = doc.read_text(encoding="utf-8")
    assert render(text) == text, "run: python -m scripts.export_ontology"
