"""Fire-and-forget trace events for Component-04 on Redis pub/sub.

    pipeline_start -> agent_end (once per agent) -> pipeline_end

Shapes match C4's app/schemas/trace_events.py (copy in app/schemas/trace_events.py).
Extra keys C4 may use: `version` on start/end, `status` on end, `traces` (every
trace line of the agent) on agent_end. With `case_id` + `version`, C4 reads the
saved result from MongoDB (collection c03_audit_results).

Publishing never blocks or breaks an audit. After a failed Redis connect the
module stays quiet for a cooldown, so a dead Redis is paid for once.
"""
import json
import logging
import threading
import time

from app import config
from app.schemas.findings import TraceEntry, now_iso

logger = logging.getLogger("c03.events")

CONNECT_TIMEOUT = 0.3
RETRY_COOLDOWN = 30.0
_redis = None
_blocked_until = 0.0
_lock = threading.Lock()


def _redis_client():
    """Shared Redis client, or None while Redis is unreachable."""
    global _redis, _blocked_until
    with _lock:
        if _redis is not None:
            return _redis
        if time.monotonic() < _blocked_until:
            return None
        try:
            import redis
            client = redis.from_url(config.REDIS_URL, decode_responses=True,
                                    socket_connect_timeout=CONNECT_TIMEOUT,
                                    socket_timeout=CONNECT_TIMEOUT)
            client.ping()
        except Exception:  # noqa: BLE001 - telemetry must never break C03
            _blocked_until = time.monotonic() + RETRY_COOLDOWN
            logger.warning("Redis at %s unreachable; trace events dropped for %.0fs.",
                           config.REDIS_URL, RETRY_COOLDOWN)
            return None
        _redis = client
        return _redis


class EventPublisher:
    """One per run, so concurrent audits never share their sent/failed state.
    Inject `client` (anything with .publish(channel, text)) in tests."""

    def __init__(self, client=None, channel: str | None = None,
                 silent_reason: str | None = None) -> None:
        self._client = client
        self.channel = channel or config.TRACE_CHANNEL
        self._silent_reason = silent_reason  # e.g. what-if runs are never sent to C4
        self._sent = 0
        self._failed = False
        self._disabled = False

    @property
    def published(self) -> bool:
        """True only when every event of this run was sent."""
        return self._sent > 0 and not self._failed and not self._disabled

    def _send(self, payload: dict) -> None:
        if self._silent_reason or (self._client is None and not config.EVENTS_ENABLED):
            self._disabled = True
            return
        client = self._client or _redis_client()
        if client is None:
            self._failed = True
            return
        try:
            client.publish(self.channel, json.dumps(payload, default=str))
            self._sent += 1
        except Exception:  # noqa: BLE001 - best-effort publish must never raise
            if not self._failed:
                logger.warning("Trace event publish failed; audit continues.")
            self._failed = True

    def note(self) -> str | None:
        """Why C4's trace is incomplete, or None when every event was sent."""
        if self._silent_reason:
            return f"Trace events not sent to C4: {self._silent_reason}."
        if self._disabled:
            return "Trace events are disabled (C03_EVENTS_ENABLED is off); C4 receives nothing."
        if self._failed:
            return "Trace event publish failed; C4's trace is incomplete (the audit is unaffected)."
        if not self.published:
            return "No trace events were sent to C4."
        return None

    def pipeline_start(self, case_id: str, doc_count: int, version: int) -> None:
        self._send({"event": "pipeline_start", "ts": now_iso(), "case_id": case_id,
                    "doc_count": doc_count, "version": version})

    def agent_end(self, case_id: str, agent: str, findings_count: int,
                  trace: list[TraceEntry]) -> None:
        entries = [t.model_dump() for t in trace]
        self._send({"event": "agent_end", "ts": now_iso(), "case_id": case_id,
                    "agent": agent, "findings_count": findings_count,
                    "trace": entries[0] if entries else {}, "traces": entries})

    def pipeline_end(self, case_id: str, total_findings: int, version: int, status: str) -> None:
        self._send({"event": "pipeline_end", "ts": now_iso(), "case_id": case_id,
                    "total_findings": total_findings, "version": version, "status": status})
