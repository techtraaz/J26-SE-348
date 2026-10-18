"""One place to call the self-hosted LLM. It only narrates trace lines; it never
decides a verdict. Any failure, timeout or unsafe line returns the fallback."""
import logging
import re
import time

from app import config

logger = logging.getLogger("c03.llm")

# Words the small model must never introduce in a trace line.
BANNED_WORDS = ("gdpr", "segregation", "sox", "hipaa", "money laundering",
                "tax fraud", "ifrs", "gaap", "pci")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
RETRY_COOLDOWN = 30.0
_blocked_until = 0.0


def is_safe(text: str, prompt: str) -> bool:
    """Short, no banned words, and every number in it was given in the prompt."""
    t = text.strip()
    if not t or len(t) > 200:
        return False
    low = t.lower()
    if any(w in low for w in BANNED_WORDS):
        return False
    given = set(_NUMBER.findall(prompt))
    return all(n in given for n in _NUMBER.findall(t))


def narrate(prompt: str, fallback: str) -> str:
    """Ask the LLM for one short line. After a failure, skip it for a cooldown so
    a dead Ollama never slows every audit."""
    global _blocked_until
    if not config.LLM_ENABLED or time.monotonic() < _blocked_until:
        return fallback
    try:
        from ollama import Client

        client = Client(host=config.OLLAMA_HOST, timeout=config.LLM_TIMEOUT)
        resp = client.chat(model=config.MODEL_NAME, messages=[
            {"role": "system", "content": "You write one short audit trace line. Only repeat "
                                          "the numbers given. Never add laws, names or facts."},
            {"role": "user", "content": f"{prompt} Max 20 words."}])
        text = (resp.message.content or "").strip().split("\n")[0]
    except Exception as exc:  # noqa: BLE001 - narration must never break an audit
        _blocked_until = time.monotonic() + RETRY_COOLDOWN
        logger.info("LLM unavailable (%s); using fallback text for %.0fs.", exc, RETRY_COOLDOWN)
        return fallback
    return text if is_safe(text, prompt) else fallback
