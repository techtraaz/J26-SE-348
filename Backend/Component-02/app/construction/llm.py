import hashlib
import json
import math
import re
from collections.abc import Callable
from typing import Protocol, TypeVar

import openai
from pydantic import BaseModel

from app.config import Settings, get_settings

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    def extract(self, system: str, user: str, schema: type[T]) -> T: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def parse_json[M: BaseModel](text: str, schema: type[M]) -> M:
    """Accept plain JSON, JSON in a code fence, or JSON with text around it."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object in the reply")
    return schema.model_validate_json(text[start:end + 1])


class OpenAICompatibleLLM:
    # not every server supports json_schema, so fall back step by step
    FORMATS = ("json_schema", "json_object", None)

    def __init__(self, settings: Settings, client=None, embed_client=None):
        self.s = settings
        self.client = client or openai.OpenAI(
            base_url=settings.llm_base_url, api_key=settings.llm_api_key,
            timeout=settings.llm_timeout)
        self.embed_client = embed_client or (
            openai.OpenAI(base_url=settings.embedding_base_url, api_key=settings.llm_api_key,
                          timeout=settings.llm_timeout)
            if settings.embedding_base_url else self.client)
        self._format = 0

    def _response_format(self, schema: type[BaseModel]) -> dict | None:
        mode = self.FORMATS[self._format]
        if mode == "json_schema":
            return {"type": "json_schema",
                    "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()}}
        return {"type": "json_object"} if mode == "json_object" else None

    def _complete(self, messages: list[dict], schema: type[BaseModel]) -> str:
        while True:
            fmt = self._response_format(schema)
            kwargs = {"response_format": fmt} if fmt else {}
            if self.s.llm_reasoning_effort:
                kwargs["reasoning_effort"] = self.s.llm_reasoning_effort
            try:
                resp = self.client.chat.completions.create(
                    model=self.s.llm_model, messages=messages,
                    temperature=self.s.llm_temperature, **kwargs)
                return resp.choices[0].message.content or ""
            except openai.BadRequestError:
                if self._format == len(self.FORMATS) - 1:
                    raise
                self._format += 1

    def extract(self, system: str, user: str, schema: type[T]) -> T:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        last_error = None
        for _ in range(self.s.llm_max_retries + 1):
            content = self._complete(messages, schema)
            try:
                return parse_json(content, schema)
            except ValueError as exc:
                last_error = exc
                messages += [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": (
                        f"That was not valid JSON for the schema: {str(exc)[:500]}. "
                        "Return only the corrected JSON.")},
                ]
        raise LLMError(f"No valid {schema.__name__} after retries: {last_error}")

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self.embed_client.embeddings.create(model=self.s.embedding_model, input=texts)
        vectors = [d.embedding for d in resp.data]
        if vectors and len(vectors[0]) != self.s.embedding_dim:
            raise LLMError(f"Embedding size {len(vectors[0])} does not match "
                           f"EMBEDDING_DIM={self.s.embedding_dim}")
        return vectors


class FakeLLM:
    """No server needed. Answers come from `responses`: a callable (user, schema) -> dict,
    or a dict of {text found in prompt: dict}. Anything else gets an empty result."""

    def __init__(self, responses: Callable | dict | None = None, dim: int = 768):
        self.responses = responses or {}
        self.dim = dim
        self.calls: list[str] = []

    def extract(self, system: str, user: str, schema: type[T]) -> T:
        self.calls.append(user)
        if callable(self.responses):
            data = self.responses(user, schema)
        else:
            data = next((v for k, v in self.responses.items() if k in user), {})
        return schema.model_validate(json.loads(json.dumps(data)))

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            seed = hashlib.sha256(text.encode()).digest()
            raw = [seed[i % len(seed)] - 127.5 + i % 7 for i in range(self.dim)]
            norm = math.sqrt(sum(v * v for v in raw)) or 1.0
            out.append([v / norm for v in raw])
        return out


def get_llm(settings: Settings | None = None) -> LLM:
    s = settings or get_settings()
    if s.llm_provider == "fake":
        return FakeLLM(dim=s.embedding_dim)
    if s.llm_provider == "openai":
        return OpenAICompatibleLLM(s)
    raise LLMError(f"Unknown LLM_PROVIDER '{s.llm_provider}', use 'openai' or 'fake'")
