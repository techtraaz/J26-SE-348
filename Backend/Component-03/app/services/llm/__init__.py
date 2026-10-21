"""One door to the self-hosted LLM, independent of which model or server runs it.

The LLM never decides a verdict. It is used for:
- explain():       the auditor-facing summary of a case, written from facts C3
                   built in code; every number in it must be one of those facts
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
from app.services import xai_trace
from app.services.llm.providers import PROVIDERS, LLMError, LLMProvider

__all__ = ["LLMError", "LLMProvider", "available", "complete_json", "explain", "is_safe",
           "narrate", "use_provider"]

logger = logging.getLogger("c03.llm")

# Words the small model must never introduce in a trace line.
BANNED_WORDS = ("gdpr", "segregation", "sox", "hipaa", "money laundering",
                "tax fraud", "ifrs", "gaap", "pci")
# A number as written: "164,673,550.00", "2,562,724", "0.30", "12".
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
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
            _provider = cls(config.LLM_BASE_URL, config.MODEL_NAME, config.LLM_API_KEY,
                            config.LLM_REASONING_EFFORT)
        return _provider


def available() -> bool:
    return _get() is not None and time.monotonic() >= _blocked_until


def _chat(system: str, user: str, schema: dict | None, timeout: float,
          purpose: str = "") -> str:
    """One LLM call. Each call is also an XAI llm_call step (when traced)."""
    global _blocked_until
    provider = _get()
    if provider is None:
        xai_trace.step("llm_call", "skipped", purpose=purpose,
                       reason="language model is turned off; rule-based fallback used")
        raise LLMError("LLM is turned off")
    if time.monotonic() < _blocked_until:
        xai_trace.step("llm_call", "skipped", purpose=purpose, model=provider.model,
                       reason="language model skipped after a recent failure")
        raise LLMError("LLM skipped after a recent failure")
    start = time.perf_counter()
    try:
        reply = provider.chat(system, user, schema, timeout)
    except LLMError as exc:
        xai_trace.step("llm_call", "error", round((time.perf_counter() - start) * 1000, 2),
                       purpose=purpose, model=provider.model, reason=str(exc))
        if provider is not _override:
            _blocked_until = time.monotonic() + config.LLM_RETRY_COOLDOWN
        raise
    xai_trace.step("llm_call", "ok", round((time.perf_counter() - start) * 1000, 2),
                   purpose=purpose, model=provider.model, prompt=user[:300], reply=reply[:300])
    return reply


def complete_json[T: BaseModel](system: str, user: str, model: type[T], timeout: float | None = None) -> T:
    """Ask for JSON matching `model`. Servers that ignore the schema still work:
    the first JSON object in the reply is taken and validated."""
    raw = _chat(system, user, model.model_json_schema(),
                config.COPILOT_LLM_TIMEOUT if timeout is None else timeout,
                purpose=f"structured {model.__name__}")
    match = _JSON_OBJECT.search(raw)
    if not match:
        raise LLMError("LLM reply had no JSON object")
    try:
        return model.model_validate(json.loads(match.group(0)))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise LLMError(f"LLM reply did not match the schema: {exc}") from exc


def _numbers(text: str) -> set[float]:
    return {float(n.replace(",", "")) for n in _NUMBER.findall(text)}


def is_safe(text: str, prompt: str, max_chars: int = 200) -> bool:
    """Not too long, no banned words, and every number in it was given in the
    prompt (compared by value, so 164,673,550 matches 164,673,550.00)."""
    t = text.strip()
    if not t or len(t) > max_chars:
        return False
    if any(w in t.lower() for w in BANNED_WORDS):
        return False
    given = _numbers(prompt)
    return all(n in given for n in _numbers(t))


EXPLAIN_SYSTEM = (
    "You are an internal audit assistant for a Sri Lankan company. From the audit facts "
    "below, write a clear summary for the auditor in plain English: what was checked, what "
    "each finding means and why it matters (use the rule, the standard and the risk given), "
    "and what the auditor should check next. Write a few short paragraphs or '-' bullet "
    "points (no numbered lists). "
    "Use only the facts given: never add numbers, laws, names, dates or facts that are not "
    "in them, and never change a finding, its severity or its status. If there are no "
    "findings, say what passed and what could not be checked.")


def explain(facts: str) -> tuple[str | None, str | None]:
    """(summary, None), or (None, why not): the LLM is off or failed, or wrote
    something unsafe (a number not in the facts, a banned word, too long)."""
    try:
        text = _chat(EXPLAIN_SYSTEM, facts, None, config.LLM_SUMMARY_TIMEOUT)
    except LLMError as exc:
        return None, str(exc)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()  # reasoning models
    if not is_safe(text, facts, config.LLM_SUMMARY_MAX_CHARS):
        return None, "the LLM's summary used a number or word not in the facts, or was too long"
    return text, None


def narrate(prompt: str, fallback: str) -> str:
    """One short trace line, or the fallback on any failure or unsafe line."""
    try:
        text = _chat("You write one short audit trace line. Only repeat the numbers "
                     "given. Never add laws, names or facts.",
                     f"{prompt} Max 20 words.", None, config.LLM_TIMEOUT,
                     purpose="summary line")
    except LLMError as exc:
        logger.info("Narration fallback: %s", exc)
        return fallback
    line = text.strip().split("\n")[0]
    return line if is_safe(line, prompt) else fallback
