"""LangGraph BaseCallbackHandler for fire-and-forget XAI trace capture.

Injected into the graph via ``config={"callbacks": [cb]}``.  Every hook
writes one document to MongoDB ``c03_callback_traces``, wrapped in a
blanket try/except so a failed write **never** blocks, slows, or crashes
the audit pipeline.

This module is entirely self-contained inside C03.  It does not import
anything from Component-04.
"""

import logging
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger("c03.xai_callback")


def _now() -> str:
    return datetime.now(UTC).isoformat()


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
    case_id : str
        The audit case being run.
    version : int
        Result version number (from ``store.next_version``).
    traces_col : pymongo.collection.Collection | None
        The ``c03_callback_traces`` collection.  Pass ``None`` to disable
        persistence entirely (e.g. MemoryStore / tests).
    """

    raise_on_error = False   # required by BaseCallbackHandler contract

    def __init__(self, case_id: str, version: int, traces_col: Any = None) -> None:
        super().__init__()
        self.case_id = case_id
        self.version = version
        self._col = traces_col
        self._seq = 0
        self._timers: dict[str, float] = {}
        self._agents: dict[str, str] = {}   # run_id -> node name, for end/error events

    # ── Core emit — fire-and-forget ───────────────────────────────────

    def _emit(self, event: dict) -> None:
        """Persist one trace document.  Swallows ALL errors."""
        self._seq += 1
        event.update(
            case_id=self.case_id,
            version=self.version,
            seq=self._seq,
        )
        if self._col is None:
            return
        try:
            self._col.insert_one(event)
        except Exception:                     # noqa: BLE001
            logger.debug("Trace write skipped (non-fatal)", exc_info=True)

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
        rid = str(run_id)
        self._timers[rid] = time.perf_counter()
        # LangGraph passes serialized=None; the node name arrives in kwargs instead.
        agent = (kwargs.get("name")
                 or (kwargs.get("metadata") or {}).get("langgraph_node")
                 or (serialized or {}).get("name")
                 or "unknown")
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
        elapsed = self._timers.pop(rid, None)
        duration_ms = round((time.perf_counter() - elapsed) * 1000, 2) if elapsed else None
        self._emit({
            "event_type": "chain_end",
            "agent": self._agents.pop(rid, None),
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
        elapsed = self._timers.pop(rid, None)
        duration_ms = round((time.perf_counter() - elapsed) * 1000, 2) if elapsed else None
        self._emit({
            "event_type": "chain_error",
            "agent": self._agents.pop(rid, None),
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
