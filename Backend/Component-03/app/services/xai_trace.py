"""XAI step tracing for Component-04, fire-and-forget.

C03 never waits on tracing. Events go onto an in-memory queue and one
background thread writes them to MongoDB in batches. When the queue is full,
or MongoDB is slow or down, events are dropped and counted; the audit and the
Copilot carry on at full speed. Component-04 reads the collection on its own.

Three pieces:
  TraceExporter  the queue and its writer thread (one per result store).
  RunTracer      one audit run or Copilot turn: stamps case, version, trace_id
                 and an ordered seq on every event.
  step()         records one granular step ("checked CHK-001 on BS-2024") from
                 anywhere inside a scope(); a no-op outside one, never raises.

TracedKG wraps a KG client so every lookup becomes a step without touching
the agents that use it.
"""
from __future__ import annotations

import atexit
import contextvars
import itertools
import logging
import queue
import threading
import time
import uuid
import weakref
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("c03.xai_trace")

SCHEMA_VERSION = 2


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


# --- exporter -----------------------------------------------------------------

_exporters: weakref.WeakSet[TraceExporter] = weakref.WeakSet()


class TraceExporter:
    """Bounded queue + one daemon writer thread. submit() never blocks.

    `collection` is called on the writer thread (opening the collection may
    need a network round trip); returning None or raising counts as MongoDB
    being down. After a failed write, events are dropped for `retry_after`
    seconds instead of waiting on a server that is not answering."""

    def __init__(self, collection: Callable[[], Any], *, max_queue: int = 10_000,
                 batch_size: int = 200, retry_after: float = 10.0) -> None:
        self._provider = collection
        self._queue: queue.Queue[dict] = queue.Queue(maxsize=max_queue)
        self._batch_size = batch_size
        self._retry_after = retry_after
        self._col: Any = None
        self._blocked_until = 0.0
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self.written = 0
        self.dropped = 0
        _exporters.add(self)

    def submit(self, doc: dict) -> bool:
        """Queue one event. False (and counted) when the queue is full, or while
        MongoDB is in its retry pause (the writer would only drop it then)."""
        self._ensure_thread()
        if time.monotonic() < self._blocked_until:
            self.dropped += 1
            return False
        try:
            self._queue.put_nowait(doc)
            return True
        except queue.Full:
            self.dropped += 1
            return False

    def flush(self, timeout: float = 2.0) -> bool:
        """Wait until every queued event was written or dropped. For tests and
        shutdown only; the request path never calls this."""
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.005)
        return True

    def _ensure_thread(self) -> None:
        if self._thread is not None:
            return
        with self._start_lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="c03-xai-exporter",
                                                daemon=True)
                self._thread.start()

    def _run(self) -> None:
        while True:
            batch = [self._queue.get()]
            while len(batch) < self._batch_size:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            try:
                self._write(batch)
            except Exception:  # noqa: BLE001 - the writer thread must never die
                self.dropped += len(batch)
            finally:
                for _ in batch:
                    self._queue.task_done()

    def _write(self, batch: list[dict]) -> None:
        now = time.monotonic()
        if now < self._blocked_until:
            self.dropped += len(batch)
            return
        try:
            if self._col is None:
                self._col = self._provider()
            if self._col is None:
                raise RuntimeError("traces collection unavailable")
            self._col.insert_many(batch, ordered=False)
            self.written += len(batch)
        except Exception as exc:  # noqa: BLE001
            self._col = None
            self._blocked_until = now + self._retry_after
            self.dropped += len(batch)
            logger.warning("XAI trace write failed (%s); dropping events for %.0fs",
                           exc, self._retry_after)


@atexit.register
def _flush_all() -> None:
    for exporter in list(_exporters):
        exporter.flush(timeout=1.0)


# --- run tracer -----------------------------------------------------------------

class RunTracer:
    """Stamps one run's events and hands them to the exporter.

    `trace_id` is unique per run, so Component-04 can tell runs of the same
    case apart (and Copilot turns from audits). `stream_id` names a second
    live stream to show the run on, e.g. the chat that started an audit of
    another case. With no exporter (memory store, tests) every call is a no-op."""

    def __init__(self, case_id: str, version: int, exporter: TraceExporter | None,
                 kind: str = "audit", stream_id: str | None = None) -> None:
        self.case_id = case_id
        self.version = version
        self.kind = kind
        self.stream_id = stream_id if stream_id != case_id else None
        self.trace_id = uuid.uuid4().hex
        self._exporter = exporter
        self._seq = itertools.count(1)
        self._lock = threading.Lock()
        self.dropped = 0  # this run's events the exporter refused

    @property
    def enabled(self) -> bool:
        return self._exporter is not None

    def note(self) -> str | None:
        """Why C4's timeline of this run may be incomplete, or None when every
        event was queued (writing finishes in the background)."""
        if not self.enabled:
            return "XAI tracing is off (no MongoDB trace store); C4 has no timeline for this run."
        if self.dropped:
            return (f"{self.dropped} XAI step(s) were dropped (trace queue full or MongoDB "
                    f"unavailable); C4's timeline for this run is incomplete. The audit is unaffected.")
        return None

    def emit(self, event: dict) -> None:
        if self._exporter is None:
            return
        try:
            event.setdefault("ts", now_iso())
            with self._lock:  # seq order == queue order, also across parallel agents
                event.update(case_id=self.case_id, version=self.version,
                             trace_id=self.trace_id, run_kind=self.kind,
                             schema=SCHEMA_VERSION, seq=next(self._seq))
                if self.stream_id:
                    event["stream_id"] = self.stream_id
                if not self._exporter.submit(event):
                    self.dropped += 1
        except Exception:
            self.dropped += 1
            logger.debug("XAI event skipped (non-fatal)", exc_info=True)


# --- steps ----------------------------------------------------------------------

_scope: contextvars.ContextVar[tuple[RunTracer, str] | None] = contextvars.ContextVar(
    "xai_scope", default=None)


def current_tracer() -> RunTracer | None:
    """The tracer of the enclosing scope, if any (e.g. the Copilot turn that
    started an audit)."""
    current = _scope.get()
    return current[0] if current else None


@contextmanager
def scope(tracer: RunTracer | None, agent: str) -> Iterator[None]:
    """Steps recorded inside belong to `agent` of `tracer`'s run."""
    if tracer is None or not tracer.enabled:
        yield
        return
    token = _scope.set((tracer, agent))
    try:
        yield
    finally:
        _scope.reset(token)


def _clean(value: Any, depth: int = 0) -> Any:
    """JSON/BSON-safe copy: anything unusual becomes a short string."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:500]
    if depth > 3:
        return str(value)[:200]
    if isinstance(value, dict):
        return {str(k): _clean(v, depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, (list, tuple, set)):
        return [_clean(v, depth + 1) for v in list(value)[:40]]
    return str(value)[:200]


def record(tracer: RunTracer, agent: str, kind: str, status: str,
           duration_ms: float | None = None, **facts: Any) -> None:
    """One step for an explicit tracer (for code running on other threads)."""
    if not tracer.enabled:
        return
    try:
        tracer.emit({"event_type": "step", "agent": agent, "kind": kind, "status": status,
                     "duration_ms": duration_ms, "facts": _clean(facts)})
    except Exception:
        logger.debug("XAI step skipped (non-fatal)", exc_info=True)


def step(kind: str, status: str, duration_ms: float | None = None, **facts: Any) -> None:
    """One step in the current scope. Outside a scope this does nothing.

    kind:   evidence_read | dq_check | kg_fetch | rule_check | policy_check |
            standard_check | evidence_link | citation_check | llm_call |
            entities | decision
    status: passed | failed | skipped | review | ok | error | info"""
    current = _scope.get()
    if current is not None:
        record(current[0], current[1], kind, status, duration_ms, **facts)


# --- KG lookups -------------------------------------------------------------------

def _kg_result(method: str, out: Any) -> dict:
    """What a lookup returned, small enough for a trace row."""
    if out is None:
        return {"found": False}
    if method in ("get_check_rules", "get_rules"):
        return {"count": len(out), "ids": [getattr(r, "rule_id", "") for r in out]}
    if method == "explain_rule":
        return {"standards": sorted({c.standard for c in out.citations if c.standard}),
                "assertions": list(out.assertions or [])}
    if method == "get_evidence_chain":
        return {"count": len(out), "ids": list(out)}
    if method == "get_standard":
        return {"code": out.code, "title": out.title, "status": out.status}
    if isinstance(out, (list, tuple, dict)):
        return {"count": len(out)}
    return {"found": True}


class TracedKG:
    """KG client proxy: every lookup is also a kg_fetch step for `agent`.

    The tracer is held explicitly (not via scope) because Reasoning runs its
    lookups on a thread pool, where context variables are not carried over."""

    _CALLS = frozenset({"get_rules", "get_check_rules", "get_evidence_chain", "explain_rule",
                        "get_field_map", "get_standard", "get_section", "get_definitions",
                        "get_line_item", "search"})

    def __init__(self, kg: Any, tracer: RunTracer, agent: str) -> None:
        self._kg = kg
        self._tracer = tracer
        self._agent = agent

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._kg, name)
        if name not in self._CALLS or not callable(attr):
            return attr

        def call(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            arg = str(args[0]) if args else ""
            try:
                out = attr(*args, **kwargs)
            except Exception as exc:
                record(self._tracer, self._agent, "kg_fetch", "error",
                       _ms(start), method=name, arg=arg, source=self._source(), error=str(exc))
                raise
            record(self._tracer, self._agent, "kg_fetch", "ok", _ms(start), method=name,
                   arg=arg, source=self._source(), result=_kg_result(name, out))
            return out

        return call

    def _source(self) -> str:
        return str(getattr(self._kg, "source", ""))


def traced_kg(kg: Any, tracer: RunTracer | None, agent: str) -> Any:
    """`kg` traced for `agent`. An already traced client (a Copilot turn's) is
    re-pointed at this run when this run is traced, else kept as it is."""
    if tracer is None or not tracer.enabled:
        return kg
    if isinstance(kg, TracedKG):
        kg = kg._kg
    return TracedKG(kg, tracer, agent)


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)
