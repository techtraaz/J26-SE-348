import openai
from fastapi.testclient import TestClient

from app.api import health
from app.config import Settings
from app.construction import llm
from app.graph import neo4j_client
from app.main import app
from app.storage import objects


def _get():
    resp = TestClient(app).get("/health")
    assert resp.status_code == 200
    return resp.json()


def test_health_reports_each_dependency(monkeypatch):
    monkeypatch.setattr(neo4j_client, "ping", lambda: False)
    monkeypatch.setattr(llm, "ping", lambda: ("up", None))
    monkeypatch.setattr(health, "_storage", lambda: ("up", "bucket uploads"))
    body = _get()
    assert body["status"] == "ok"
    assert (body["neo4j"], body["llm"], body["storage"]) == ("down", "up", "up")
    assert "neo4j" in body["details"] and "llm" not in body["details"]


def test_storage_not_configured_and_down(monkeypatch):
    def missing():
        raise objects.StorageNotConfigured("x")
    monkeypatch.setattr(objects, "get_store", missing)
    assert health._storage()[0] == "not configured"

    class Broken:
        bucket = "uploads"

        def ping(self):
            raise objects.StorageError("Object storage unreachable: EndpointConnectionError")
    monkeypatch.setattr(objects, "get_store", lambda: Broken())
    assert health._storage() == ("down", "Object storage unreachable: EndpointConnectionError")


def test_llm_ping(monkeypatch):
    assert llm.ping(Settings(llm_provider="fake"))[0] == "fake"

    class Models:
        def __init__(self, ids=None):
            self.ids = ids

        def list(self):
            if self.ids is None:
                raise openai.APIConnectionError(request=None)
            return [type("M", (), {"id": i}) for i in self.ids]

    def client(models):
        return lambda **_: type("C", (), {"models": models})()

    s = Settings(llm_provider="openai", llm_model="qwen")
    monkeypatch.setattr(openai, "OpenAI", client(Models()))
    assert llm.ping(s)[0] == "down"
    monkeypatch.setattr(openai, "OpenAI", client(Models(["qwen"])))
    assert llm.ping(s) == ("up", None)
    monkeypatch.setattr(openai, "OpenAI", client(Models(["other"])))
    assert llm.ping(s)[0] == "up" and "not in" in llm.ping(s)[1]
