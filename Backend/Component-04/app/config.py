"""Single place for all Component 04 settings.

Reads from environment variables with sensible defaults so the service
runs out of the box for local development (Redis on localhost, SQLite
file next to the project root).

Supports .env files via python-dotenv if installed.
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
# Redis (Event Bus)
# ---------------------------------------------------------------------------
REDIS_URL: str = os.getenv("C04_REDIS_URL", "redis://localhost:6379/0")
TRACE_CHANNEL: str = os.getenv("C04_TRACE_CHANNEL", "nomos:trace_events")

# ---------------------------------------------------------------------------
# SQLite (Middle DB — local trace storage, still used as fast local cache)
# ---------------------------------------------------------------------------
_default_db = str(Path(__file__).resolve().parent.parent / "trace_store.db")
DATABASE_PATH: str = os.getenv("C04_DATABASE_PATH", _default_db)

# ---------------------------------------------------------------------------
# MongoDB Atlas (Remote persistent storage)
# ---------------------------------------------------------------------------
MONGODB_URI: str = os.getenv(
    "C04_MONGODB_URI",
    "mongodb+srv://subhashana55555_db_user:Rfvecj2z7vDxskdw@cluster0.gjjqh1i.mongodb.net/",
)
MONGODB_DB_NAME: str = os.getenv("C04_MONGODB_DB_NAME", "nomos_xai")

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
# Minimum number of agent_end events to consider the audit "complex enough"
INSIGHT_MIN_AGENTS: int = int(os.getenv("C04_INSIGHT_MIN_AGENTS", "2"))
# Minimum total findings to justify generating an insight summary
INSIGHT_MIN_FINDINGS: int = int(os.getenv("C04_INSIGHT_MIN_FINDINGS", "1"))

