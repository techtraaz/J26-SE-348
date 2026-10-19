"""Single place for all settings. Values can be overridden in .env."""
import os
import re
from pathlib import Path

_INLINE_COMMENT = re.compile(r"\s+#.*$")


def parse_dotenv(text: str) -> dict[str, str]:
    """KEY=VALUE lines (no extra library). A '#' after a space starts a comment,
    so `KG_TIMEOUT=5   # seconds` gives 5; a '#' inside a value (a password in a
    URI) is kept. Quoted values are taken as written."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if value[:1] in ("'", '"') and value[0] in value[1:]:
            value = value[1:value.index(value[0], 1)]
        else:
            value = _INLINE_COMMENT.sub("", value)
        out[key.strip()] = value
    return out


def _load_dotenv(path: Path) -> None:
    if path.exists():
        for key, value in parse_dotenv(path.read_text(encoding="utf-8")).items():
            os.environ.setdefault(key, value)


def _flag(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


_load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# --- LLM (self-hosted; narrates and reads requests, never decides a verdict) --
# Provider: ollama | openai (any self-hosted OpenAI-compatible server: llama.cpp,
# vLLM, LM Studio) | none. Swap the model here, no code change.
LLM_ENABLED: bool = _flag("C03_LLM_ENABLED", True)
LLM_PROVIDER: str = os.getenv("C03_LLM_PROVIDER", "ollama").lower()
MODEL_NAME: str = os.getenv("C03_LLM_MODEL", os.getenv("C03_MODEL_NAME", "phi4-mini"))
LLM_BASE_URL: str = os.getenv("C03_LLM_BASE_URL", os.getenv(
    "OLLAMA_HOST", "http://localhost:11434" if LLM_PROVIDER == "ollama" else "http://localhost:8080/v1"))
LLM_API_KEY: str = os.getenv("C03_LLM_API_KEY", "")  # only if the local server needs one
LLM_TIMEOUT: float = float(os.getenv("C03_LLM_TIMEOUT", "8"))  # audit trace narration
COPILOT_LLM_TIMEOUT: float = float(os.getenv("C03_COPILOT_LLM_TIMEOUT", "25"))  # first call loads the model
LLM_RETRY_COOLDOWN: float = float(os.getenv("C03_LLM_RETRY_COOLDOWN", "30"))

# --- Copilot -------------------------------------------------------------------
# auto  -> rules decide when confident, otherwise the LLM (rules if it fails)
# rules -> never the LLM      llm -> always ask the LLM (rules if it fails)
COPILOT_NLU: str = os.getenv("C03_COPILOT_NLU", "auto").lower()
# Rules are "confident" with a top score >= this and a lead >= the margin.
COPILOT_RULES_CONFIDENT_SCORE: float = float(os.getenv("C03_COPILOT_RULES_SCORE", "2.5"))
COPILOT_RULES_MARGIN: float = float(os.getenv("C03_COPILOT_RULES_MARGIN", "1.0"))
# In auto mode the LLM chooses among the rules' top N intents (all when none scored).
COPILOT_LLM_CANDIDATES: int = int(os.getenv("C03_COPILOT_LLM_CANDIDATES", "3"))
COPILOT_MAX_ITEMS: int = 10  # findings / cases listed in one reply
# Fields read from a sentence are less certain than extracted documents.
WHATIF_FIELD_CONFIDENCE: float = 0.6

# A C1 line matched to a field by the LLM and not confirmed by a person keeps at
# most this confidence: below REVIEW_CONFIDENCE_LIMIT, so it becomes a REV-001
# review item and every finding using it needs more evidence.
UNCONFIRMED_MAPPING_CONFIDENCE: float = 0.4

# NEVER let the LLM write free Cypher at run time. Locked.
ALLOW_FREE_CYPHER: bool = False

# --- Knowledge graph (Component-02) ----------------------------------------
#   auto -> try live, use mock only when C2 is unreachable (marked mock_fallback)
#   mock -> never touch the network
#   live -> never fall back; KG problems become visible REV-007 findings
KG_MODE: str = os.getenv("KG_MODE", "auto")
KG_URL: str = os.getenv("KG_URL", "")  # C2 base URL, e.g. http://localhost:8002
KG_TIMEOUT: float = float(os.getenv("KG_TIMEOUT", "5"))
# How C2 searches the standards for the Copilot: keyword | semantic | hybrid.
# hybrid uses C2's embeddings and falls back to keyword (with a note) when they are off.
KG_SEARCH_MODE: str = os.getenv("KG_SEARCH_MODE", "hybrid").lower()

# C2's DocumentType codes (Component-02 seed 05_audit.yaml) plus "unknown".
ALLOWED_DOC_TYPES: frozenset[str] = frozenset({
    "balance_sheet", "income_statement", "cash_flow_statement", "equity_statement",
    "trial_balance", "general_ledger", "invoice", "receipt", "payment_voucher",
    "bank_statement", "purchase_order", "goods_received_note",
    "fixed_asset_register", "payroll", "unknown",
})

# CHK-006 (required fields), checked in code by Data Quality because its KG
# expression is prose. Each entry lists the names a document may use.
REQUIRED_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "balance_sheet": {
        "assets": ("assets", "total_assets"),
        "liabilities": ("liabilities", "total_liabilities"),
        "capital": ("capital", "equity", "total_equity"),
    },
    "invoice": {"amount": ("amount",)},
    "receipt": {"amount": ("amount",)},
    "payment_voucher": {"amount": ("amount",)},
    "trial_balance": {"debit_total": ("debit_total", "total_debits"),
                      "credit_total": ("credit_total", "total_credits")},
    "general_ledger": {"debit_total": ("debit_total", "total_debits"),
                       "credit_total": ("credit_total", "total_credits")},
}

# Fields the engine does maths on. Intake parses them to numbers; a value that
# still is not a number is surfaced for review (REV-003), never guessed.
NUMERIC_FIELDS: frozenset[str] = frozenset({
    "amount", "cash_out", "asset_in",
    "assets", "total_assets", "liabilities", "total_liabilities",
    "capital", "equity", "total_equity",
    "debit_total", "total_debits", "credit_total", "total_credits",
    "current_assets", "total_current_assets", "total_non_current_assets",
    "revenue", "sales", "turnover", "cost_of_sales", "cogs", "gross_profit",
    "cash", "cash_and_cash_equivalents", "closing_cash", "closing_equity",
    "inventories", "inventory", "closing_inventory", "inventory_nrv", "inventory_cost",
})

# C2 check rules carry no category, so C3 maps the ones it knows.
# Rules in the possible_fraud category run in the Anomaly agent.
RULE_CATEGORY: dict[str, str] = {
    "CHK-001": "ledger", "CHK-002": "ledger",
    "CHK-003": "arithmetic", "CHK-004": "arithmetic",
    "CHK-005": "possible_fraud",
}
DEFAULT_RULE_CATEGORY: str = "compliance"

# KG rules C3 checks in code instead of evaluating the expression.
CODE_CHECKED_RULES: frozenset[str] = frozenset({"CHK-006"})

# Field a KG policy limit (e.g. POL-07) is compared against.
POLICY_LIMIT_FIELD: str = "amount"

# Equality tolerance for money (1 cent).
AMOUNT_TOLERANCE: float = 0.01

# Below this confidence a finding needs more evidence, not a silent pass.
REVIEW_CONFIDENCE_LIMIT: float = 0.5

FINDINGS_STATUS_DEFAULT: str = "pending_auditor_review"

# --- Result store (FR6: every version kept) ----------------------------------
MONGODB_URI: str = os.getenv("C03_MONGODB_URI", "")
MONGODB_DB: str = os.getenv("C03_MONGODB_DB", "nomos_xai")
MONGODB_TIMEOUT_MS: int = int(os.getenv("C03_MONGODB_TIMEOUT_MS", "5000"))
RESULTS_COLLECTION: str = "c03_audit_results"
COUNTERS_COLLECTION: str = "c03_version_counters"
# mongo -> MongoDB (fails loudly when unreachable); memory -> process only (tests/dev)
STORE_MODE: str = os.getenv("C03_STORE_MODE", "mongo" if MONGODB_URI else "memory")

# --- Trace events for Component-04 (Redis pub/sub, best-effort) ------------
EVENTS_ENABLED: bool = _flag("C03_EVENTS_ENABLED", True)
REDIS_URL: str = os.getenv("C03_REDIS_URL", "redis://localhost:6379/0")
TRACE_CHANNEL: str = os.getenv("C03_TRACE_CHANNEL", "nomos:trace_events")

# --- API ---------------------------------------------------------------------
CORS_ORIGINS: list[str] = [o.strip() for o in os.getenv(
    "C03_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
