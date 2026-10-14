"""One place to call the LLM. Never decides pass/fail, only explains."""
from app import config


def explain_with_llm(prompt: str, fallback: str) -> str:
    """Try Ollama, else return fallback. So tests pass even if Ollama is off."""
    try:
        from ollama import chat
        resp = chat(model=config.MODEL_NAME,
                    messages=[{"role": "user", "content": prompt}])
        text = (resp.message.content or "").strip()
        return text if text else fallback
    except Exception:
        return fallback
