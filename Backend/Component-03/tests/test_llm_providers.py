"""LLM providers: what is sent to the server and what is kept of the reply."""
import json

from app.services.llm.providers import (
    OllamaProvider,
    OpenAICompatibleProvider,
    answer_only,
)


class _Resp:
    def __init__(self, content):
        self._body = json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _capture(monkeypatch, content):
    sent = {}

    def fake_urlopen(req, timeout):
        sent["body"] = json.loads(req.data)
        sent["auth"] = req.get_header("Authorization")
        return _Resp(content)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return sent


def test_reasoning_effort_is_sent_only_when_set(monkeypatch):
    sent = _capture(monkeypatch, '{"intent": "help"}')
    OpenAICompatibleProvider("http://gpu/v1", "qwen3.5:35b", "tok", "none").chat("s", "u", {"type": "object"}, 5)
    assert sent["body"]["reasoning_effort"] == "none" and sent["auth"] == "Bearer tok"
    OpenAICompatibleProvider("http://local/v1", "phi4-mini").chat("s", "u", None, 5)
    assert "reasoning_effort" not in sent["body"]  # phi4-mini setup unchanged


def test_thinking_text_never_reaches_the_answer(monkeypatch):
    _capture(monkeypatch, '<think>maybe {"intent": "x"}?</think>\n{"intent": "help"}')
    assert OpenAICompatibleProvider("http://gpu/v1", "qwen").chat("s", "u", None, 5) == '{"intent": "help"}'
    assert answer_only("no thinking here") == "no thinking here"


def test_ollama_turns_thinking_off_only_when_asked(monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, host, timeout):
            pass

        def chat(self, **kw):
            calls.append(kw)
            return type("R", (), {"message": type("M", (), {"content": "<think>x</think>ok"})()})()
    monkeypatch.setattr("ollama.Client", FakeClient)
    assert OllamaProvider("http://h", "qwen3.5:35b", reasoning_effort="none").chat("s", "u", None, 5) == "ok"
    assert calls[-1]["think"] is False
    OllamaProvider("http://h", "phi4-mini").chat("s", "u", None, 5)
    assert "think" not in calls[-1]
