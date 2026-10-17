"""Fast, offline tests: LLM never called (mocked), so no Ollama wait.
Agents call llm.explain_with_llm via module reference, so one patch covers all."""
import pytest


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    import app.services.llm as llm_mod

    def fast(prompt: str, fallback: str) -> str:
        return fallback

    monkeypatch.setattr(llm_mod, "explain_with_llm", fast)


@pytest.fixture(autouse=True)
def _no_real_events(monkeypatch):
    # Keep the default publisher silent; tests that check events inject a client.
    from app import config
    monkeypatch.setattr(config, "EVENTS_ENABLED", False)
