"""In-memory SSE broadcast manager, partitioned by case_id.

Each connected frontend client opens an SSE stream for a specific case.
The subscriber calls ``broadcast()`` after every DB write, which fans
the enriched trace out to every queue registered for that case_id.

Design:
  - One ``asyncio.Queue`` per connected client.
  - Queues are grouped by case_id in a dict-of-sets.
  - ``subscribe()`` is an async generator that yields trace dicts
    as they arrive — the SSE endpoint wraps this in an EventSourceResponse.
  - When a client disconnects, its queue is automatically discarded.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, AsyncGenerator

logger = logging.getLogger("c04.sse")

# case_id → set of asyncio.Queue (one per connected client)
_subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)


async def broadcast(case_id: str, data: dict[str, Any]) -> None:
    """Push a trace payload to every client listening on this case_id.

    Non-blocking: if a client's queue is full the event is dropped for
    that client (backpressure protection).
    """
    listeners = _subscribers.get(case_id)
    if not listeners:
        return
    for queue in list(listeners):  # snapshot to avoid mutation during iter
        try:
            queue.put_nowait(data)
        except asyncio.QueueFull:
            logger.warning("Dropped event for a slow SSE client on case=%s", case_id)


async def subscribe(case_id: str) -> AsyncGenerator[dict[str, Any], None]:
    """Async generator that yields trace events for a given case_id.

    Usage (inside the SSE endpoint)::

        async for payload in sse_manager.subscribe(case_id):
            yield {"event": "trace", "data": json.dumps(payload)}
    """
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
    _subscribers[case_id].add(queue)
    logger.info("SSE client connected  case=%s  (total=%d)", case_id, len(_subscribers[case_id]))
    try:
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
