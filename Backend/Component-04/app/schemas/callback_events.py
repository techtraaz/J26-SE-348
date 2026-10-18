"""Pydantic models for callback trace events written by C03's XAITracerCallback.

C03 writes these documents to MongoDB ``c03_callback_traces``.  C04 reads
them via the trace reader and deserialises into these typed structures.

Event types:
  - pipeline_start  : audit begins, includes doc_count
  - chain_start     : a graph node (agent) begins
  - chain_end       : a graph node finishes, includes findings/output summary
  - chain_error     : an agent raised an exception
  - llm_start       : an LLM call begins (only if C03 uses LangChain wrappers)
  - llm_end         : LLM response received
  - llm_error       : LLM call failed
  - pipeline_end    : full audit complete, includes total_findings and status
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


EventType = Literal[
    "pipeline_start", "pipeline_end",
    "chain_start", "chain_end", "chain_error",
    "llm_start", "llm_end", "llm_error",
]


class CallbackEvent(BaseModel):
    """A single trace event from C03's XAITracerCallback."""

    event_type: EventType
    case_id: str
    version: int = 1
    seq: int = 0
    ts: str = ""

    # chain events
    agent: str | None = None
    run_id: str | None = None
    parent_run_id: str | None = None
    duration_ms: float | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    # llm events
    model: str | None = None
    prompt_preview: str | None = None
    response_preview: str | None = None

    # error events
    error: str | None = None

    # pipeline events
    doc_count: int | None = None
    total_findings: int | None = None
    status: str | None = None


def parse_callback_event(raw: dict[str, Any]) -> CallbackEvent:
    """Deserialise a raw MongoDB document into a typed CallbackEvent.

    Strips MongoDB's ``_id`` field before validation.
    Raises ``ValueError`` for unknown or malformed events.
    """
    cleaned = {k: v for k, v in raw.items() if k != "_id"}
    return CallbackEvent(**cleaned)
