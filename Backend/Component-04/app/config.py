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
