"""LangGraph BaseCallbackHandler for fire-and-forget XAI trace capture.

Injected into the graph via ``config={"callbacks": [cb]}``.  Every hook
hands one event to the run's RunTracer, which queues it for a background
writer (see xai_trace.py): the audit never waits on MongoDB, and a failed
write never blocks, slows, or crashes the pipeline.

Only the graph's agent nodes are reported. The root graph run and routing
functions (e.g. route_after_dq) are LangGraph internals, not agents.

This module is entirely self-contained inside C03.  It does not import
anything from Component-04.
"""

import logging
import time
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from app.services.xai_trace import RunTracer, now_iso

logger = logging.getLogger("c03.xai_callback")


def _now() -> str:
    return now_iso()


def _safe_summary(obj: Any, max_len: int = 800) -> dict:
    """Extract a JSON-safe summary from chain outputs without dumping raw case data."""
    if obj is None:
        return {}
    summary: dict[str, Any] = {}
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key == "case":
                continue                    # never dump the full input case
            if isinstance(val, list):
                summary[f"{key}_count"] = len(val)
                # Trace entries: their human-readable lines are the agent's summary
                if val and hasattr(val[0], "detail"):
                    summary[f"{key}_details"] = [str(v.detail)[:300] for v in val[:5]]
                # Grab first-item preview for trace / findings lists
                if val and hasattr(val[0], "model_dump"):
                    first = val[0].model_dump()
                    summary[f"{key}_preview"] = str(first)[:max_len]
                elif val and isinstance(val[0], dict):
                    summary[f"{key}_preview"] = str(val[0])[:max_len]
            elif isinstance(val, bool):
                summary[key] = val
            elif isinstance(val, (int, float)):
                summary[key] = val
            elif isinstance(val, str) and len(val) <= max_len:
                summary[key] = val
    return summary


class XAITracerCallback(BaseCallbackHandler):
    """Fire-and-forget trace capture.  Never blocks, never raises, never
    crashes C03.  Every public method is wrapped so that a MongoDB failure
    is silently logged and the audit continues undisturbed.

    Parameters
    ----------
    tracer : RunTracer
        The run's tracer (case, version, trace_id, ordered seq).  A tracer
        without an exporter (MemoryStore / tests) makes every hook a no-op.
    """

    raise_on_error = False   # required by BaseCallbackHandler contract

    def __init__(self, tracer: RunTracer) -> None:
        super().__init__()
        self.tracer = tracer
        self._timers: dict[str, float] = {}
        self._agents: dict[str, str] = {}   # run_id -> node name, for end/error events

    # ── Core emit — fire-and-forget ───────────────────────────────────

    def _emit(self, event: dict) -> None:
        """Queue one trace event.  Never blocks, swallows ALL errors."""
        self.tracer.emit(event)

    # ── Graph node lifecycle ──────────────────────────────────────────

    def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        # LangGraph passes serialized=None; the node name arrives in kwargs instead.
        # Only agent nodes count: the root graph has no langgraph_node, and a
        # routing function runs under its node with a different run name.
        node = (kwargs.get("metadata") or {}).get("langgraph_node")
        name = kwargs.get("name") or (serialized or {}).get("name")
        if not node or (name and name != node):
            return
        rid = str(run_id)
        agent = node
        self._timers[rid] = time.perf_counter()
        self._agents[rid] = agent
        self._emit({
            "event_type": "chain_start",
            "agent": agent,
            "run_id": rid,
            "parent_run_id": str(parent_run_id) if parent_run_id else None,
            "ts": _now(),
        })

    def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        rid = str(run_id)
        agent = self._agents.pop(rid, None)
        if agent is None:
            return  # not an agent node (see on_chain_start)
        elapsed = self._timers.pop(rid, None)
        duration_ms = round((time.perf_counter() - elapsed) * 1000, 2) if elapsed else None
        self._emit({
            "event_type": "chain_end",
            "agent": agent,
            "run_id": rid,
            "parent_run_id": str(parent_run_id) if parent_run_id else None,
            "duration_ms": duration_ms,
            "data": _safe_summary(outputs),
            "ts": _now(),
        })

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        rid = str(run_id)
        agent = self._agents.pop(rid, None)
        if agent is None:
            return  # not an agent node (see on_chain_start)
        elapsed = self._timers.pop(rid, None)
        duration_ms = round((time.perf_counter() - elapsed) * 1000, 2) if elapsed else None
        self._emit({
            "event_type": "chain_error",
            "agent": agent,
            "run_id": rid,
            "parent_run_id": str(parent_run_id) if parent_run_id else None,
            "duration_ms": duration_ms,
            "error": str(error)[:500],
            "ts": _now(),
        })

    # ── LLM lifecycle (fires only if C03 wraps calls in LangChain) ────

    def on_llm_start(
        self,
        serialized: dict[str, Any] | None,
        prompts: list[str],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        rid = str(run_id)
        self._timers[rid] = time.perf_counter()
        self._emit({
            "event_type": "llm_start",
            "model": (serialized or {}).get("name") or ((serialized or {}).get("id") or ["unknown"])[-1],
            "prompt_preview": prompts[0][:500] if prompts else "",
            "run_id": rid,
            "parent_run_id": str(parent_run_id) if parent_run_id else None,
            "ts": _now(),
        })

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        rid = str(run_id)
        elapsed = self._timers.pop(rid, None)
        duration_ms = round((time.perf_counter() - elapsed) * 1000, 2) if elapsed else None
        # Extract text from LangChain LLMResult
        text = ""
        try:
            text = str(response.generations[0][0].text)[:500]
        except Exception:                     # noqa: BLE001
            text = str(response)[:500]
        self._emit({
            "event_type": "llm_end",
            "response_preview": text,
            "run_id": rid,
            "parent_run_id": str(parent_run_id) if parent_run_id else None,
            "duration_ms": duration_ms,
            "ts": _now(),
        })

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        rid = str(run_id)
        elapsed = self._timers.pop(rid, None)
        duration_ms = round((time.perf_counter() - elapsed) * 1000, 2) if elapsed else None
        self._emit({
            "event_type": "llm_error",
            "error": str(error)[:500],
            "run_id": rid,
            "parent_run_id": str(parent_run_id) if parent_run_id else None,
            "duration_ms": duration_ms,
            "ts": _now(),
        })
