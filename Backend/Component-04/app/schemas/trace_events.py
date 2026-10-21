"""Pydantic models for trace events — now driven by C03's XAITracerCallback.

This module re-exports the callback event models for backward compatibility.
The actual models live in ``app.schemas.callback_events``.

Old architecture:  C03 → Redis pub/sub → C04 subscriber (3 event types)
New architecture:  C03 → XAITracerCallback → MongoDB → C04 trace_reader (8+ event types)
"""

from app.schemas.callback_events import CallbackEvent, EventType, parse_callback_event

__all__ = ["CallbackEvent", "EventType", "parse_callback_event"]
