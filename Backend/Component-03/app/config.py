"""Single place for all settings. Change model here only."""
import os
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Read simple KEY=VALUE lines into the environment (no extra library)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# Ollama model name. Start with phi4-mini, change later in 1 place.
MODEL_NAME: str = "phi4-mini"

# NEVER let the LLM write free Cypher at run time. Small models make mistakes.
ALLOW_FREE_CYPHER: bool = False

# Knowledge-graph access mode:
#   auto -> try live, fall back to mock ONLY on connection errors/timeouts
#   mock -> never touch the network
#   live -> never fall back; errors surface
KG_MODE: str = os.getenv("KG_MODE", "auto")
KG_URL: str = os.getenv("KG_URL", "")
KG_TIMEOUT: float = float(os.getenv("KG_TIMEOUT", "5"))

# Doc types the KG will answer for. Anything else is rejected, never guessed.
ALLOWED_DOC_TYPES: frozenset[str] = frozenset({
    "balance_sheet", "income_statement", "invoice", "receipt",
    "voucher", "ledger", "unknown",
})

# Year-to-year jump limit (30%). If change is bigger, flag it.
YEAR_CHANGE_LIMIT: float = 0.30

# Small number tolerance for float maths (1 cent).
AMOUNT_TOLERANCE: float = 0.01

# API version tag for findings. Old versions are kept, never overwritten.
FINDINGS_STATUS_DEFAULT: str = "pending_auditor_review"
