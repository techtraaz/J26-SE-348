"""In-memory SSE broadcast manager, partitioned by stream id (a case id or a
chat session id).

Each connected frontend client opens an SSE stream for a specific case.
The trace reader calls ``broadcast()`` for every event, which fans the
enriched trace out to every queue registered for that stream.

Design:
  - One ``asyncio.Queue`` per connected client.
  - Queues are grouped by stream id in a dict-of-sets.
  - ``subscribe()`` is an async generator that yields trace dicts
    as they arrive — the SSE endpoint wraps this in an EventSourceResponse.
  - When a client disconnects, its queue is automatically discarded.
  - Each stream keeps a bounded history of its recent events, replayed to a
    client when it connects, so opening the panel mid-run (or reopening it
    after a run) still shows every step so far. Bounded per stream and in
    the number of streams kept, so memory stays flat.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict, defaultdict, deque
from typing import Any, AsyncGenerator

logger = logging.getLogger("c04.sse")

HISTORY_PER_STREAM = 1500   # events replayed to a new client
HISTORY_STREAMS = 256       # streams whose history is kept (least recent dropped)
CLIENT_QUEUE_SIZE = 2048    # an audit can emit a few hundred steps in one burst

# stream_id → set of asyncio.Queue (one per connected client)
_subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)

# stream_id → recent events, most recently used stream last
_history: OrderedDict[str, deque[dict[str, Any]]] = OrderedDict()


def _remember(stream_id: str, data: dict[str, Any]) -> None:
    events = _history.get(stream_id)
    if events is None:
        events = _history[stream_id] = deque(maxlen=HISTORY_PER_STREAM)
        while len(_history) > HISTORY_STREAMS:
            _history.popitem(last=False)
    else:
        _history.move_to_end(stream_id)
    events.append(data)


async def broadcast(case_id: str, data: dict[str, Any]) -> None:
    """Push a trace payload to every client listening on this stream.

    Non-blocking: if a client's queue is full the event is dropped for
    that client (backpressure protection).
    """
    _remember(case_id, data)
    listeners = _subscribers.get(case_id)
    if not listeners:
        return
    for queue in list(listeners):  # snapshot to avoid mutation during iter
        try:
            queue.put_nowait(data)
        except asyncio.QueueFull:
            logger.warning("Dropped event for a slow SSE client on case=%s", case_id)


def history(case_id: str) -> list[dict[str, Any]]:
    """The stream's recent events, oldest first."""
    return list(_history.get(case_id, ()))


async def subscribe(case_id: str, replay: bool = True) -> AsyncGenerator[dict[str, Any], None]:
    """Async generator that yields trace events for a given stream.

    With ``replay`` the stream's recent history comes first. The snapshot is
    taken and the queue registered in one step (no await in between), so no
    event is lost or delivered twice.

    Usage (inside the SSE endpoint)::

        async for payload in sse_manager.subscribe(case_id):
            yield {"event": "trace", "data": json.dumps(payload)}
    """
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=CLIENT_QUEUE_SIZE)
    backlog = history(case_id) if replay else []
    _subscribers[case_id].add(queue)
    logger.info("SSE client connected  case=%s  (total=%d, replay=%d)",
                case_id, len(_subscribers[case_id]), len(backlog))
    try:
        for payload in backlog:
            yield payload
        while True:
            payload = await queue.get()
            yield payload
    except asyncio.CancelledError:
        pass
    finally:
        _subscribers[case_id].discard(queue)
        if not _subscribers[case_id]:
            del _subscribers[case_id]
        logger.info("SSE client disconnected  case=%s", case_id)


def active_case_ids() -> list[str]:
    """Return a list of case_ids that currently have SSE listeners."""
    return list(_subscribers.keys())
