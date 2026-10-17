"""Fire-and-forget trace events for Component-04.

C03 publishes three event types on the Redis channel C4 subscribes to
(`nomos:trace_events`; see C4 app/schemas/trace_events.py):

    pipeline_start -> agent_end (once per agent) -> pipeline_end

Publishing is best-effort: it never blocks or breaks an audit. If Redis (or the
`redis` package) is unavailable, events are dropped and logged, never raised.

Inject a client for tests via EventPublisher(client=...). Without one, the real
transport is Component-04's `app.services.telemetry` module, so both modules
share a single Redis publisher and events are never sent twice.
"""
import json
import logging
from datetime import UTC, datetime

from app import config
from app.services import telemetry

logger = logging.getLogger("c03.events")


def _now() -> str:
    return datetime.now(UTC).isoformat()


class EventPublisher:
    """Publishes JSON events. An injected client captures them directly."""

    def __init__(self, client=None, channel: str | None = None):
        self._client = client
        self._injected = client is not None
        self._warned = False
        self.channel = channel or config.TRACE_CHANNEL

    def publish(self, payload: dict) -> None:
        """Send raw JSON to the injected client. A no-op without one."""
        if not self._injected:
            return
        try:
            self._client.publish(self.channel, json.dumps(payload, default=str))
        except Exception:  # noqa: BLE001 - best-effort publish must never raise
            if not self._warned:
                logger.warning("Trace event publish failed; continuing audit.")
                self._warned = True

    def pipeline_start(self, case_id: str, doc_count: int) -> None:
        if self._injected:
            return self.publish({"event": "pipeline_start", "ts": _now(),
                                 "case_id": case_id, "doc_count": doc_count})
        if config.EVENTS_ENABLED:
            telemetry.emit_pipeline_start(case_id, doc_count)

    def agent_end(self, case_id: str, agent: str, findings_count: int,
                  trace: dict) -> None:
        if self._injected:
            return self.publish({"event": "agent_end", "ts": _now(),
                                 "case_id": case_id, "agent": agent,
                                 "findings_count": findings_count, "trace": trace})
        if config.EVENTS_ENABLED:
            telemetry.emit_agent_end(case_id, agent, findings_count, trace)

    def pipeline_end(self, case_id: str, total_findings: int) -> None:
        if self._injected:
            return self.publish({"event": "pipeline_end", "ts": _now(),
                                 "case_id": case_id, "total_findings": total_findings})
        if config.EVENTS_ENABLED:
            telemetry.emit_pipeline_end(case_id, total_findings)


_publisher = EventPublisher()


def default_publisher() -> EventPublisher:
    return _publisher
