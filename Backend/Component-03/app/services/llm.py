"""One place to call the LLM. Never decides pass/fail, only explains."""
from app import config

# Words the small model must never invent in trace lines.
BANNED_WORDS = ("gdpr", "segregation", "sox", "hipaa", "money laundering",
                "tax fraud", "ifrs", "gaap", "pci")


def _is_safe(text: str, fallback: str) -> bool:
    """Short, no banned words, no new big claims. Else use fallback."""
    t = text.strip()
    if not t or len(t) > 200:
        return False
    low = t.lower()
    for w in BANNED_WORDS:
        if w in low:
            return False
    return True


def explain_with_llm(prompt: str, fallback: str) -> str:
    """Try Ollama, else return fallback. So tests pass even if Ollama is off."""
    try:
        from ollama import chat
        strict = (
            "You write a trace note. Rules: one short line, max 20 words. "
            "Only repeat the numbers given. Do not add new laws, countries, "
            "regulations, or company names. No GDPR. No new facts.\n"
            f"Task: {prompt}"
        )
        resp = chat(model=config.MODEL_NAME,
                    messages=[{"role": "system",
                               "content": "You are a strict trace writer. Only repeat given numbers. Never invent facts."},
                              {"role": "user", "content": strict}])
        text = (resp.message.content or "").strip().split("\n")[0]
        if _is_safe(text, fallback):
            return text
        return fallback
    except Exception:
        return fallback
