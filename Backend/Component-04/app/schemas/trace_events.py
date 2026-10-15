"""Pydantic models for events arriving on the Redis 'nomos:trace_events' channel.

Component 03 broadcasts three event types in fire-and-forget fashion:
  - pipeline_start : marks the beginning of an audit run
  - agent_end      : emitted after each agent finishes its work
  - pipeline_end   : marks the completion of the full audit pipeline

These models mirror what C03 publishes.  C04 deserialises the raw JSON
into these typed structures before any enrichment or persistence.
"""

from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, Field


# ── Individual event models ────────────────────────────────────────────

class PipelineStartEvent(BaseModel):
    """Broadcast when the orchestrator begins a new case."""

    event: Literal["pipeline_start"]
    ts: str = Field(description="ISO-8601 UTC timestamp set by the broadcaster in C03")
    case_id: str
    doc_count: int = 0


class AgentEndEvent(BaseModel):
    """Broadcast after each agent returns its (findings, trace) tuple."""

    event: Literal["agent_end"]
    ts: str
    case_id: str
    agent: str = Field(description="Agent name: data_quality | compliance | anomaly | reasoning | evidence_validation")
    findings_count: int = 0
    trace: dict[str, Any] = Field(
        default_factory=dict,
        description="Raw TraceEntry payload from C03 (agent_name, decision_type, detail)",
    )


class PipelineEndEvent(BaseModel):
    """Broadcast when the full pipeline completes."""

    event: Literal["pipeline_end"]
    ts: str
    case_id: str
    total_findings: int = 0


# ── Discriminated union for safe parsing ───────────────────────────────

TraceEvent = Union[PipelineStartEvent, AgentEndEvent, PipelineEndEvent]
"""Use ``parse_trace_event()`` below instead of constructing directly."""


def parse_trace_event(raw: dict[str, Any]) -> TraceEvent:
    """Deserialise a raw JSON dict from Redis into the correct typed model.

    Uses the ``event`` field as a discriminator.  Raises ``ValueError``
    for unknown or malformed events so the subscriber can log and skip.
    """
    event_type = raw.get("event")
    match event_type:
        case "pipeline_start":
            return PipelineStartEvent(**raw)
        case "agent_end":
            return AgentEndEvent(**raw)
        case "pipeline_end":
            return PipelineEndEvent(**raw)
        case _:
            raise ValueError(f"Unknown trace event type: {event_type!r}")
