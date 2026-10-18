"""Offline tests: no LLM, no Redis, no MongoDB, no live KG."""
import pytest

from app import config
from app.services import chat_store as chat_store_mod
from app.services import store as store_mod
from app.services.kg_client import FallbackKGClient, MockKGClient


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(config, "LLM_ENABLED", False)
    monkeypatch.setattr(config, "EVENTS_ENABLED", False)
    monkeypatch.setattr(config, "KG_MODE", "mock")
    monkeypatch.setattr(config, "KG_URL", "")
    monkeypatch.setattr(config, "MONGODB_URI", "")
    monkeypatch.setattr(config, "STORE_MODE", "memory")
    monkeypatch.setattr(store_mod, "_store", store_mod.MemoryStore())
    monkeypatch.setattr(chat_store_mod, "_chats", chat_store_mod.MemoryChatStore())


@pytest.fixture
def kg():
    return FallbackKGClient(mode="mock", mock=MockKGClient())


@pytest.fixture
def store():
    return store_mod.default_store()


@pytest.fixture
def chats():
    return chat_store_mod.default_chat_store()


class FakeRedis:
    def __init__(self, fail: bool = False):
        self.sent: list[tuple[str, str]] = []
        self.fail = fail

    def publish(self, channel, text):
        if self.fail:
            raise ConnectionError("redis down")
        self.sent.append((channel, text))


def doc(doc_id, doc_type, fields, year=2026, **extra):
    return {"doc_id": doc_id, "doc_type": doc_type, "period_year": year, "fields": fields, **extra}
