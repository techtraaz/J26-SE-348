"""Fire-and-forget trace events for Component-04.

C03 publishes three event types on the Redis channel C4 subscribes to
(`nomos:trace_events`; see C4 app/schemas/trace_events.py):

    pipeline_start -> agent_end (once per agent) -> pipeline_end

Publishing is best-effort: it never blocks or breaks an audit. If Redis (or the
`redis` package) is unavailable, events are dropped and logged, never raised.

The publisher also tracks whether it actually sent anything, so the audit
result can say `events_published` and a trace line can record when C4 got
nothing (disabled or failed).

Inject a client for tests via EventPublisher(client=...). Without one, the real
transport is this component's `app.services.telemetry` module, so both modules
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
        self.channel = channel or config.TRACE_CHANNEL
        self.reset()

    def reset(self) -> None:
        """Clear per-run state. Called at the start of every pipeline.

        run_case/stream_case build a fresh publisher per run, so two concurrent
        audits never share these flags; this is defensive for reuse too.
        """
        self._sent = 0
        self._disabled = False
        self._failed = False
        self._warned = False

    @property
    def published(self) -> bool:
        """True only when every event of this run was sent (no drop, no disable)."""
        return self._sent > 0 and not self._failed and not self._disabled

    def _record(self, ok: bool) -> None:
        if ok:
            self._sent += 1
        else:
            self._failed = True

    def publish(self, payload: dict) -> None:
        """Send raw JSON to the injected client. A no-op without one."""
        if not self._injected:
            return
        try:
            self._client.publish(self.channel, json.dumps(payload, default=str))
            self._record(True)
        except Exception:  # noqa: BLE001 - best-effort publish must never raise
            self._record(False)
            if not self._warned:
                logger.warning("Trace event publish failed; continuing audit.")
                self._warned = True

    def note(self) -> str | None:
        """Why C4 got no (or incomplete) events, or None when all is well."""
        if self._failed:
            return ("Trace event publish failed; C4's trace is incomplete "
                    "(the audit itself is unaffected).")
        if self._disabled:
            return ("Trace events are disabled (C03_EVENTS_ENABLED is off); "
                    "C4 receives nothing.")
        if not self.published:
            return "No trace events were sent to C4."
        return None

    def pipeline_start(self, case_id: str, doc_count: int) -> None:
        self.reset()
        if self._injected:
            self.publish({"event": "pipeline_start", "ts": _now(),
                          "case_id": case_id, "doc_count": doc_count})
            return
        if not config.EVENTS_ENABLED:
            self._disabled = True
            return
        self._record(telemetry.emit_pipeline_start(case_id, doc_count))

    def agent_end(self, case_id: str, agent: str, findings_count: int,
                  trace: dict) -> None:
        if self._injected:
            self.publish({"event": "agent_end", "ts": _now(),
                          "case_id": case_id, "agent": agent,
                          "findings_count": findings_count, "trace": trace})
            return
        if not config.EVENTS_ENABLED:
            self._disabled = True
            return
        self._record(telemetry.emit_agent_end(case_id, agent, findings_count, trace))

    def pipeline_end(self, case_id: str, total_findings: int) -> None:
        if self._injected:
            self.publish({"event": "pipeline_end", "ts": _now(),
                          "case_id": case_id, "total_findings": total_findings})
            return
        if not config.EVENTS_ENABLED:
            self._disabled = True
            return
        self._record(telemetry.emit_pipeline_end(case_id, total_findings))


_publisher = EventPublisher()


def default_publisher() -> EventPublisher:
    return _publisher
