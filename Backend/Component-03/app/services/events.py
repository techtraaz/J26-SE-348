"""Fire-and-forget trace events for Component-04.

C03 publishes three event types on the Redis channel C4 subscribes to
(`nomos:trace_events`; see C4 app/schemas/trace_events.py):

    pipeline_start -> agent_end (once per agent) -> pipeline_end

Publishing is best-effort: it never blocks or breaks an audit. If Redis (or the
`redis` package) is unavailable, events are dropped and logged, never raised.
Inject a client for tests via EventPublisher(client=...).
"""
import json
import logging
from datetime import UTC, datetime

from app import config

logger = logging.getLogger("c03.events")


def _now() -> str:
    return datetime.now(UTC).isoformat()


class EventPublisher:
    """Publishes JSON events. The default client is a lazily-built Redis one."""

    def __init__(self, client=None, channel: str | None = None):
        self._client = client
        self._resolved = client is not None
        self._warned = False
        self.channel = channel or config.TRACE_CHANNEL

    def _get_client(self):
        if self._resolved:
            return self._client
        self._resolved = True
        if not config.EVENTS_ENABLED:
            return None
        try:
            import redis  # local import: optional dependency
        except ImportError:
            logger.warning("redis package not installed; trace events disabled.")
            return None
        try:
            self._client = redis.Redis.from_url(config.REDIS_URL)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Could not create Redis client; events disabled.")
        return self._client

    def publish(self, payload: dict) -> None:
        client = self._get_client()
        if client is None:
            return
        try:
            client.publish(self.channel, json.dumps(payload, default=str))
        except Exception:  # noqa: BLE001 - best-effort publish must never raise
            if not self._warned:
                logger.warning("Trace event publish failed; continuing audit.")
                self._warned = True

    def pipeline_start(self, case_id: str, doc_count: int) -> None:
        self.publish({"event": "pipeline_start", "ts": _now(),
                      "case_id": case_id, "doc_count": doc_count})

    def agent_end(self, case_id: str, agent: str, findings_count: int,
                  trace: dict) -> None:
        self.publish({"event": "agent_end", "ts": _now(), "case_id": case_id,
                      "agent": agent, "findings_count": findings_count,
                      "trace": trace})

    def pipeline_end(self, case_id: str, total_findings: int) -> None:
        self.publish({"event": "pipeline_end", "ts": _now(),
                      "case_id": case_id, "total_findings": total_findings})


_publisher = EventPublisher()


def default_publisher() -> EventPublisher:
    return _publisher
