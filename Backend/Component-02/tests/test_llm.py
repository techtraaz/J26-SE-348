import math
from types import SimpleNamespace

import httpx
import openai
import pytest

from app.config import Settings
from app.construction.documents import Chunk
from app.construction.llm import FakeLLM, LLMError, OpenAICompatibleLLM, get_llm, parse_json
from app.construction.prompts import SYSTEM, build_user_prompt
from app.construction.schema import ChunkExtraction, ExtractionContext

GOOD = ('{"is_normative": true, "requirements": [{"text": "Measure inventories at the lower '
        'of cost and NRV", "type": "measurement", "obligation": "shall", '
        '"applies_to": ["inventories"]}]}')


def _settings(**kw):
    return Settings(_env_file=None, llm_provider="openai", embedding_dim=4, **kw)


class StubClient:
    """Mimics openai.OpenAI: replies are returned in order, calls are recorded."""

    def __init__(self, replies=(), vectors=None):
        self.replies = list(replies)
        self.calls = []
        self.vectors = vectors or []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.embeddings = SimpleNamespace(create=self._embed)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])

    def _embed(self, **kwargs):
        return SimpleNamespace(data=[SimpleNamespace(embedding=v) for v in self.vectors])


def _bad_request():
    req = httpx.Request("POST", "http://test/v1/chat/completions")
    return openai.BadRequestError("format not supported", response=httpx.Response(400, request=req),
                                  body=None)


def test_parse_json_accepts_fences_and_surrounding_text():
    assert parse_json(f"```json\n{GOOD}\n```", ChunkExtraction).is_normative
    assert parse_json(f"Here you go: {GOOD} done", ChunkExtraction).requirements[0].type == "measurement"
    with pytest.raises(ValueError):
        parse_json("no json here", ChunkExtraction)


def test_extract_sends_json_schema_and_parses():
    client = StubClient([GOOD])
    llm = OpenAICompatibleLLM(_settings(), client=client)
    out = llm.extract("sys", "user", ChunkExtraction)
    assert out.requirements[0].applies_to == ["inventories"]
    fmt = client.calls[0]["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["name"] == "ChunkExtraction"
    assert client.calls[0]["temperature"] == 0.0
    assert "reasoning_effort" not in client.calls[0]


def test_reasoning_effort_is_sent_when_set():
    client = StubClient([GOOD])
    OpenAICompatibleLLM(_settings(llm_reasoning_effort="none"), client=client).extract(
        "s", "u", ChunkExtraction)
    assert client.calls[0]["reasoning_effort"] == "none"


def test_invalid_reply_is_retried_with_feedback():
    client = StubClient(['{"requirements": [{"text": "x", "type": "made_up"}]}', GOOD])
    out = OpenAICompatibleLLM(_settings(), client=client).extract("sys", "user", ChunkExtraction)
    assert out.is_normative
    assert "not valid JSON" in client.calls[1]["messages"][-1]["content"]


def test_gives_up_after_retries():
    client = StubClient(["nope", "nope", "nope"])
    with pytest.raises(LLMError):
        OpenAICompatibleLLM(_settings(llm_max_retries=2), client=client).extract("s", "u", ChunkExtraction)


def test_falls_back_when_server_rejects_json_schema():
    client = StubClient([_bad_request(), GOOD])
    OpenAICompatibleLLM(_settings(), client=client).extract("s", "u", ChunkExtraction)
    assert client.calls[1]["response_format"] == {"type": "json_object"}


def test_embedding_size_must_match_setting():
    ok = OpenAICompatibleLLM(_settings(), client=StubClient(vectors=[[0.1, 0.2, 0.3, 0.4]]))
    assert len(ok.embed(["a"])[0]) == 4
    bad = OpenAICompatibleLLM(_settings(), client=StubClient(vectors=[[0.1, 0.2]]))
    with pytest.raises(LLMError, match="EMBEDDING_DIM"):
        bad.embed(["a"])


def test_fake_llm_scripted_and_default():
    fake = FakeLLM({"LKAS 2:9": {"is_normative": True}})
    assert fake.extract("s", "chunk LKAS 2:9", ChunkExtraction).is_normative
    assert fake.extract("s", "other", ChunkExtraction) == ChunkExtraction()
    assert len(fake.calls) == 2


def test_fake_embeddings_are_stable_and_normalised():
    fake = FakeLLM(dim=768)
    a, b = fake.embed(["same text", "same text"])
    assert a == b and len(a) == 768
    assert math.isclose(sum(v * v for v in a), 1.0, rel_tol=1e-9)


def test_get_llm_by_provider():
    assert isinstance(get_llm(Settings(_env_file=None, llm_provider="fake")), FakeLLM)
    assert isinstance(get_llm(Settings(_env_file=None, llm_provider="openai")), OpenAICompatibleLLM)
    with pytest.raises(LLMError):
        get_llm(Settings(_env_file=None, llm_provider="ollama"))


def test_prompt_contains_codes_text_and_ocr_warning():
    chunk = Chunk(id="LKAS 2:9", file="f.pdf", page=5, number="9", heading="Measurement",
                  text="9  Inventories shall be measured at the lower of cost and NRV.",
                  confidence=0.4)
    ctx = ExtractionContext(line_items=["inventories"], known=["LKAS 2:9#R1 lower of cost and NRV"])
    prompt = build_user_prompt(chunk, "LKAS 2", ctx)
    assert "Allowed line items: inventories" in prompt
    assert "Allowed document types: (none)" in prompt
    assert "OCR with low confidence" in prompt
    assert prompt.rstrip().endswith('"""') and chunk.text in prompt
    assert "Return one JSON object only" in SYSTEM and '"is_normative"' in SYSTEM


def test_schema_limits_requirement_types():
    schema = ChunkExtraction.model_json_schema()
    req = schema["$defs"]["ExtractedRequirement"]["properties"]
    assert set(req["type"]["enum"]) >= {"recognition", "measurement", "disclosure"}
    assert req["obligation"]["enum"] == ["shall", "should", "may"]
