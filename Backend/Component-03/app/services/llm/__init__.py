"""One door to the self-hosted LLM, independent of which model or server runs it.

The LLM never decides a verdict. It is used for:
- narrate():       one short trace line (falls back to fixed text)
- complete_json(): structured reading of a request, validated against a
                   Pydantic model; anything that does not fit raises LLMError

After a failure the LLM is skipped for a cooldown, so a dead server never slows
every call. Tests and evaluations can swap the provider with use_provider().
"""
import json
import logging
import re
import threading
import time

from pydantic import BaseModel, ValidationError

from app import config
from app.services.llm.providers import PROVIDERS, LLMError, LLMProvider

__all__ = ["LLMError", "LLMProvider", "available", "complete_json", "is_safe", "narrate",
           "use_provider"]

logger = logging.getLogger("c03.llm")

# Words the small model must never introduce in a trace line.
BANNED_WORDS = ("gdpr", "segregation", "sox", "hipaa", "money laundering",
                "tax fraud", "ifrs", "gaap", "pci")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

_lock = threading.Lock()
_provider: LLMProvider | None = None
_override: LLMProvider | None = None
_blocked_until = 0.0


def use_provider(provider: LLMProvider | None) -> None:
    """Force a provider (tests, evaluation). None returns to the configured one."""
    global _override, _blocked_until
    with _lock:
        _override = provider
        _blocked_until = 0.0


def _get() -> LLMProvider | None:
    global _provider
    if _override is not None:
        return _override
    if not config.LLM_ENABLED or config.LLM_PROVIDER == "none":
        return None
    with _lock:
        if _provider is None or (_provider.name, _provider.model, _provider.base_url) != (
                config.LLM_PROVIDER, config.MODEL_NAME, config.LLM_BASE_URL.rstrip("/")):
            cls = PROVIDERS.get(config.LLM_PROVIDER)
            if cls is None:
                logger.warning("Unknown C03_LLM_PROVIDER %r; LLM off.", config.LLM_PROVIDER)
                return None
            _provider = cls(config.LLM_BASE_URL, config.MODEL_NAME, config.LLM_API_KEY)
        return _provider


def available() -> bool:
    return _get() is not None and time.monotonic() >= _blocked_until


def _chat(system: str, user: str, schema: dict | None, timeout: float) -> str:
    global _blocked_until
    provider = _get()
    if provider is None:
        raise LLMError("LLM is turned off")
    if time.monotonic() < _blocked_until:
        raise LLMError("LLM skipped after a recent failure")
    try:
        return provider.chat(system, user, schema, timeout)
    except LLMError:
        if provider is not _override:
            _blocked_until = time.monotonic() + config.LLM_RETRY_COOLDOWN
        raise


def complete_json[T: BaseModel](system: str, user: str, model: type[T], timeout: float | None = None) -> T:
    """Ask for JSON matching `model`. Servers that ignore the schema still work:
    the first JSON object in the reply is taken and validated."""
    raw = _chat(system, user, model.model_json_schema(),
                config.COPILOT_LLM_TIMEOUT if timeout is None else timeout)
    match = _JSON_OBJECT.search(raw)
    if not match:
        raise LLMError("LLM reply had no JSON object")
    try:
        return model.model_validate(json.loads(match.group(0)))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise LLMError(f"LLM reply did not match the schema: {exc}") from exc


def is_safe(text: str, prompt: str) -> bool:
    """Short, no banned words, and every number in it was given in the prompt."""
    t = text.strip()
    if not t or len(t) > 200:
        return False
    if any(w in t.lower() for w in BANNED_WORDS):
        return False
    given = set(_NUMBER.findall(prompt))
    return all(n in given for n in _NUMBER.findall(t))


def narrate(prompt: str, fallback: str) -> str:
    """One short trace line, or the fallback on any failure or unsafe line."""
    try:
        text = _chat("You write one short audit trace line. Only repeat the numbers "
                     "given. Never add laws, names or facts.",
                     f"{prompt} Max 20 words.", None, config.LLM_TIMEOUT)
    except LLMError as exc:
        logger.info("Narration fallback: %s", exc)
        return fallback
    line = text.strip().split("\n")[0]
    return line if is_safe(line, prompt) else fallback
