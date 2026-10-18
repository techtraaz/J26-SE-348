"""LLM providers. Each turns (system, user, optional JSON schema) into raw text.

Only self-hosted servers are expected (NFR2): Ollama, or any OpenAI-compatible
server such as llama.cpp, vLLM or LM Studio. Add a provider by subclassing
LLMProvider and listing it in PROVIDERS.
"""
import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod


class LLMError(RuntimeError):
    """The LLM is off, unreachable, too slow, or replied with something unusable."""


class LLMProvider(ABC):
    name: str = "base"

    def __init__(self, base_url: str, model: str, api_key: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key

    @abstractmethod
    def chat(self, system: str, user: str, schema: dict | None, timeout: float) -> str:
        """One deterministic (temperature 0) chat turn. Raises LLMError."""


class OllamaProvider(LLMProvider):
    name = "ollama"

    def chat(self, system, user, schema, timeout):
        try:
            from ollama import Client

            resp = Client(host=self.base_url, timeout=timeout).chat(
                model=self.model, format=schema, options={"temperature": 0},
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}])
        except Exception as exc:
            raise LLMError(f"ollama: {exc}") from exc
        return resp.message.content or ""


class OpenAICompatibleProvider(LLMProvider):
    """POST {base_url}/chat/completions (llama.cpp, vLLM, LM Studio, ...)."""

    name = "openai"

    def chat(self, system, user, schema, timeout):
        body: dict = {"model": self.model, "temperature": 0,
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": user}]}
        if schema is not None:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "output", "schema": schema}}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(f"{self.base_url}/chat/completions",
                                     data=json.dumps(body).encode("utf-8"), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"] or ""
        except (urllib.error.URLError, TimeoutError, OSError, KeyError, IndexError,
                json.JSONDecodeError) as exc:
            raise LLMError(f"openai-compatible: {exc}") from exc


PROVIDERS: dict[str, type[LLMProvider]] = {
    OllamaProvider.name: OllamaProvider,
    OpenAICompatibleProvider.name: OpenAICompatibleProvider,
}
