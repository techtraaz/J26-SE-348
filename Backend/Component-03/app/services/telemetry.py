"""Fire-and-forget telemetry broadcaster for Component 04.

Publishes trace events to the ``nomos:trace_events`` Redis Pub/Sub channel
so the XAI Trace Collector (Component 04) can passively capture them.

CRITICAL SAFETY CONTRACT:
  - Every public function silently swallows ALL exceptions.
  - If Redis is offline, unreachable, or misconfigured, Component 03
    continues running without any disruption.
  - This module is a pure side-effect — it never returns data that
    C03's business logic depends on.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

logger = logging.getLogger("c03.telemetry")

# ── Configuration ──────────────────────────────────────────────────────

_REDIS_URL = os.getenv("C03_REDIS_URL", "redis://localhost:6379/0")
_CHANNEL = os.getenv("C03_TRACE_CHANNEL", "nomos:trace_events")

# ── Lazy Redis client (created on first use) ──────────────────────────

_client = None


def _get_client():
    """Lazy-init a synchronous Redis client. Returns None on failure."""
    global _client
    if _client is not None:
        return _client
    try:
        import redis
        _client = redis.from_url(_REDIS_URL, decode_responses=True)
        _client.ping()
        logger.info("Telemetry connected to Redis at %s", _REDIS_URL)
        return _client
    except Exception:  # noqa: BLE001 - telemetry must never break C03
        logger.debug("Telemetry: Redis unavailable — events will be silently dropped")
        return None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _publish(payload: dict) -> None:
    """Publish a JSON payload to the trace channel. Never raises."""
    try:
        client = _get_client()
        if client is None:
            return
        client.publish(_CHANNEL, json.dumps(payload, default=str))
    except Exception:
        # Swallow everything — C03 must never be affected
        logger.debug("Telemetry publish failed (non-fatal)", exc_info=True)


# ── Public API (fire-and-forget) ───────────────────────────────────────

def emit_pipeline_start(case_id: str, doc_count: int) -> None:
    """Call at the beginning of run_case."""
    _publish({
        "event": "pipeline_start",
        "ts": _now(),
        "case_id": case_id,
        "doc_count": doc_count,
    })


def emit_agent_end(
    case_id: str,
    agent: str,
    findings_count: int,
    trace: dict | None = None,
) -> None:
    """Call immediately after each agent returns."""
    _publish({
        "event": "agent_end",
        "ts": _now(),
        "case_id": case_id,
        "agent": agent,
        "findings_count": findings_count,
        "trace": trace or {},
    })


def emit_pipeline_end(case_id: str, total_findings: int) -> None:
    """Call right before returning the final AuditResult."""
    _publish({
        "event": "pipeline_end",
        "ts": _now(),
        "case_id": case_id,
        "total_findings": total_findings,
    })
