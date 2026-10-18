"""Single place for all Component 04 settings.

Reads from environment variables with sensible defaults so the service
runs out of the box for local development (MongoDB shared with C03,
SQLite file next to the project root).
"""

import os
from pathlib import Path

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

# ---------------------------------------------------------------------------
# MongoDB Atlas (shared with C03 — reads callback traces written by C03)
# ---------------------------------------------------------------------------
MONGODB_URI: str = os.getenv(
    "C04_MONGODB_URI",
    os.getenv("C03_MONGODB_URI", ""),
)
MONGODB_DB_NAME: str = os.getenv("C04_MONGODB_DB_NAME", "nomos_xai")
C03_TRACES_COLLECTION: str = "c03_callback_traces"
TRACE_POLL_INTERVAL_MS: int = int(os.getenv("C04_TRACE_POLL_MS", "300"))

# ---------------------------------------------------------------------------
# SQLite (Middle DB — C04's own local trace storage)
# ---------------------------------------------------------------------------
_default_db = str(Path(__file__).resolve().parent.parent / "trace_store.db")
DATABASE_PATH: str = os.getenv("C04_DATABASE_PATH", _default_db)

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
HOST: str = os.getenv("C04_HOST", "0.0.0.0")
PORT: int = int(os.getenv("C04_PORT", "8004"))

# ---------------------------------------------------------------------------
# Cloud LLM (Phi-4 on remote GPU via Cloudflare Tunnel)
# ---------------------------------------------------------------------------
LLM_API_URL: str = os.getenv(
    "C04_LLM_API_URL",
    "https://described-completing-classroom-fans.trycloudflare.com/api/chat",
)
LLM_MODEL: str = os.getenv("C04_LLM_MODEL", "phi4")
LLM_TIMEOUT: int = int(os.getenv("C04_LLM_TIMEOUT", "60"))

# ---------------------------------------------------------------------------
# Insight Generator (Smart Filter Thresholds)
# ---------------------------------------------------------------------------
INSIGHT_MIN_AGENTS: int = int(os.getenv("C04_INSIGHT_MIN_AGENTS", "2"))
INSIGHT_MIN_FINDINGS: int = int(os.getenv("C04_INSIGHT_MIN_FINDINGS", "1"))
