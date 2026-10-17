"""Tests for the LLM guard. Real explain_with_llm, fake ollama module, offline."""
import sys
import types

import pytest


@pytest.fixture(autouse=True)
def _mock_llm():
    # Override conftest's stub so the real explain_with_llm runs in this module.
    yield


def _fake_ollama(monkeypatch, reply=None, boom=None):
    if boom is not None:
        def chat(**kwargs):
            raise boom
    else:
        def chat(**kwargs):
            return types.SimpleNamespace(
                message=types.SimpleNamespace(content=reply))
    mod = types.ModuleType("ollama")
    mod.chat = chat
    monkeypatch.setitem(sys.modules, "ollama", mod)


def test_safe_short_reply_is_returned(monkeypatch):
    _fake_ollama(monkeypatch, reply="Assets equal liabilities plus capital.")
    from app.services.llm import explain_with_llm
    assert explain_with_llm("explain", "fallback") == \
        "Assets equal liabilities plus capital."


def test_only_first_line_is_used(monkeypatch):
    _fake_ollama(monkeypatch, reply="one short line\nextra chatter ignored")
    from app.services.llm import explain_with_llm
    assert explain_with_llm("explain", "fallback") == "one short line"


def test_banned_word_falls_back(monkeypatch):
    _fake_ollama(monkeypatch, reply="This violates GDPR rules.")
    from app.services.llm import explain_with_llm
    assert explain_with_llm("explain", "fallback") == "fallback"


def test_over_length_falls_back(monkeypatch):
    _fake_ollama(monkeypatch, reply="x" * 201)
    from app.services.llm import explain_with_llm
    assert explain_with_llm("explain", "fallback") == "fallback"


def test_empty_reply_falls_back(monkeypatch):
    _fake_ollama(monkeypatch, reply="   ")
    from app.services.llm import explain_with_llm
    assert explain_with_llm("explain", "fallback") == "fallback"


def test_ollama_down_falls_back(monkeypatch):
    _fake_ollama(monkeypatch, boom=RuntimeError("connection refused"))
    from app.services.llm import explain_with_llm
    assert explain_with_llm("explain", "fallback") == "fallback"
