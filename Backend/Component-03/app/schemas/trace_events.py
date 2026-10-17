"""C4 trace-event contract, copied (not imported) so C3 can test its own output.

These models mirror Component-04's `app/schemas/trace_events.py`. Project rule:
never import code across components — copy the shapes instead. If the contract
drifts, the C3 contract test fails before C4 ever sees a bad event.

C03 broadcasts three event types, fire-and-forget:
  - pipeline_start : beginning of an audit run
  - agent_end      : emitted after each agent finishes
  - pipeline_end   : end of the full pipeline
"""
from typing import Any, Literal

from pydantic import BaseModel, Field


class PipelineStartEvent(BaseModel):
    event: Literal["pipeline_start"]
    ts: str = Field(description="ISO-8601 UTC timestamp set by C03")
    case_id: str
    doc_count: int = 0


class AgentEndEvent(BaseModel):
    event: Literal["agent_end"]
    ts: str
    case_id: str
    agent: str
    findings_count: int = 0
    trace: dict[str, Any] = Field(default_factory=dict)


class PipelineEndEvent(BaseModel):
    event: Literal["pipeline_end"]
    ts: str
    case_id: str
    total_findings: int = 0


TraceEvent = PipelineStartEvent | AgentEndEvent | PipelineEndEvent


def parse_trace_event(raw: dict[str, Any]) -> TraceEvent:
    """Deserialise a raw event dict using the `event` discriminator."""
    match raw.get("event"):
        case "pipeline_start":
            return PipelineStartEvent(**raw)
        case "agent_end":
            return AgentEndEvent(**raw)
        case "pipeline_end":
            return PipelineEndEvent(**raw)
        case other:
            raise ValueError(f"Unknown trace event type: {other!r}")
