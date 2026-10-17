from fastapi.testclient import TestClient

from app.graph import neo4j_client
from app.main import app


def test_health_reports_neo4j_status(monkeypatch):
    monkeypatch.setattr(neo4j_client, "ping", lambda: False)
    resp = TestClient(app).get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "neo4j": "down"}
