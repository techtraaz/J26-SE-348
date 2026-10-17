"""Fire-and-forget telemetry broadcaster for Component 04.

Publishes trace events to the ``nomos:trace_events`` Redis Pub/Sub channel
so the XAI Trace Collector (Component 04) can passively capture them.

CRITICAL SAFETY CONTRACT:
  - Every public function swallows ALL exceptions and returns a bool.
  - If Redis is offline, unreachable, or misconfigured, Component 03
    continues running without any disruption.
  - This module is a pure side-effect — it never returns data that
    C03's business logic depends on, only whether an event was sent.

Connect attempts are cheap but not free: each one is bounded by short
timeouts, and after a failure the module stays quiet for a cooldown window
so a dead Redis never adds latency to every audit.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime

logger = logging.getLogger("c03.telemetry")

# ── Configuration ──────────────────────────────────────────────────────

_REDIS_URL = os.getenv("C03_REDIS_URL", "redis://localhost:6379/0")
_CHANNEL = os.getenv("C03_TRACE_CHANNEL", "nomos:trace_events")

# Short timeouts so a dead/slow Redis never stalls the audit pipeline.
CONNECT_TIMEOUT = 0.3
SOCKET_TIMEOUT = 0.3
# After a failed connect, do not try again for this long.
RETRY_COOLDOWN = 30.0

# ── Lazy Redis client (created on first use) ──────────────────────────

_client = None
_blocked_until = 0.0
_connect_attempts = 0


def _connect():
    """Create a Redis client. Separate from _get_client so tests can stub it."""
    import redis
    return redis.from_url(_REDIS_URL, decode_responses=True,
                          socket_connect_timeout=CONNECT_TIMEOUT,
                          socket_timeout=SOCKET_TIMEOUT)


def _get_client():
    """Lazy-init a synchronous Redis client. Returns None on failure.

    After a failed connect the module refuses to retry for RETRY_COOLDOWN
    seconds, so a dead Redis is paid for once, not on every event."""
    global _client, _blocked_until, _connect_attempts
    if _client is not None:
        return _client
    now = time.monotonic()
    if now < _blocked_until:
        return None
    _connect_attempts += 1
    try:
        client = _connect()
        client.ping()
    except Exception:  # telemetry must never break C03
        _blocked_until = now + RETRY_COOLDOWN
        logger.warning(
            "Telemetry: Redis at %s is unreachable; events dropped, no retry "
            "for %.0fs.", _REDIS_URL, RETRY_COOLDOWN, exc_info=True)
        return None
    _client = client
    logger.info("Telemetry connected to Redis at %s", _REDIS_URL)
    return _client


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _publish(payload: dict) -> bool:
    """Publish one payload. True if sent, False if disabled/dropped. Never raises."""
    try:
        client = _get_client()
        if client is None:
            return False
        client.publish(_CHANNEL, json.dumps(payload, default=str))
        return True
    except Exception:  # C03 must never be affected
        logger.warning("Telemetry publish failed; event dropped.", exc_info=True)
        return False


# ── Public API (fire-and-forget; bool = was it published) ──────────────

def emit_pipeline_start(case_id: str, doc_count: int) -> bool:
    """Call at the beginning of run_case."""
    return _publish({
        "event": "pipeline_start",
        "ts": _now(),
        "case_id": case_id,
        "doc_count": doc_count,
    })


def emit_agent_end(case_id: str, agent: str, findings_count: int,
                   trace: dict | None = None) -> bool:
    """Call immediately after each agent returns."""
    return _publish({
        "event": "agent_end",
        "ts": _now(),
        "case_id": case_id,
        "agent": agent,
        "findings_count": findings_count,
        "trace": trace or {},
    })


def emit_pipeline_end(case_id: str, total_findings: int) -> bool:
    """Call right before returning the final AuditResult."""
    return _publish({
        "event": "pipeline_end",
        "ts": _now(),
        "case_id": case_id,
        "total_findings": total_findings,
    })
