"""Single place for all Component 04 settings.

Reads from environment variables with sensible defaults so the service
runs out of the box for local development (Redis on localhost, SQLite
file next to the project root).
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Redis (Event Bus)
# ---------------------------------------------------------------------------
REDIS_URL: str = os.getenv("C04_REDIS_URL", "redis://localhost:6379/0")
TRACE_CHANNEL: str = os.getenv("C04_TRACE_CHANNEL", "nomos:trace_events")

# ---------------------------------------------------------------------------
# SQLite (Middle DB — local trace storage)
# ---------------------------------------------------------------------------
_default_db = str(Path(__file__).resolve().parent.parent / "trace_store.db")
DATABASE_PATH: str = os.getenv("C04_DATABASE_PATH", _default_db)

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
HOST: str = os.getenv("C04_HOST", "0.0.0.0")
PORT: int = int(os.getenv("C04_PORT", "8004"))

# ---------------------------------------------------------------------------
# Local LLM (Ollama — shared with Component 03)
# ---------------------------------------------------------------------------
LLM_API_URL: str = os.getenv("C04_LLM_API_URL", "http://localhost:11434/api/chat")
LLM_MODEL: str = os.getenv("C04_LLM_MODEL", "phi4-mini")
LLM_TIMEOUT: int = int(os.getenv("C04_LLM_TIMEOUT", "30"))

# ---------------------------------------------------------------------------
# Insight Generator (Smart Filter Thresholds)
# ---------------------------------------------------------------------------
# Minimum number of agent_end events to consider the audit "complex enough"
INSIGHT_MIN_AGENTS: int = int(os.getenv("C04_INSIGHT_MIN_AGENTS", "2"))
# Minimum total findings to justify generating an insight summary
INSIGHT_MIN_FINDINGS: int = int(os.getenv("C04_INSIGHT_MIN_FINDINGS", "1"))
