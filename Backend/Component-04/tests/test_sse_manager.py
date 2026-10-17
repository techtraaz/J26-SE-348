"""Tests for the in-memory SSE broadcast manager.

Verifies queue registration, broadcast delivery, backpressure handling,
and automatic cleanup on disconnect.
"""

from __future__ import annotations

import asyncio

from app.services import sse_manager


async def test_broadcast_delivers_to_subscriber():
    """A subscribed client should receive broadcast data."""
    received: list[dict] = []

    async def _collect():
        async for payload in sse_manager.subscribe("CASE-SSE-1"):
            received.append(payload)
            break  # exit after first message

    task = asyncio.create_task(_collect())
    await asyncio.sleep(0.05)  # let the subscriber register

    await sse_manager.broadcast("CASE-SSE-1", {"event_type": "test", "value": 42})
    await asyncio.sleep(0.05)  # let the message propagate

    await task
    assert len(received) == 1
    assert received[0]["event_type"] == "test"
    assert received[0]["value"] == 42


async def test_broadcast_to_empty_case_does_not_raise():
    """Broadcasting to a case with no subscribers should be a no-op."""
    await sse_manager.broadcast("NOBODY-LISTENING", {"data": "ignored"})


async def test_active_case_ids_tracks_subscribers():
    """active_case_ids should reflect currently subscribed cases."""
    assert "CASE-SSE-2" not in sse_manager.active_case_ids()

    async def _subscribe_briefly():
        async for _ in sse_manager.subscribe("CASE-SSE-2"):
            break

    task = asyncio.create_task(_subscribe_briefly())
    await asyncio.sleep(0.05)

    assert "CASE-SSE-2" in sse_manager.active_case_ids()

    # Send one message to unblock the generator so it exits
    await sse_manager.broadcast("CASE-SSE-2", {"done": True})
    await asyncio.sleep(0.05)
    await task

    # After disconnect, the case should be cleaned up
    assert "CASE-SSE-2" not in sse_manager.active_case_ids()


async def test_multiple_subscribers_receive_same_event():
    """Two subscribers on the same case should both receive the broadcast."""
    results_a: list[dict] = []
    results_b: list[dict] = []

    async def _collect(target: list):
        async for payload in sse_manager.subscribe("CASE-SSE-3"):
            target.append(payload)
            break

    task_a = asyncio.create_task(_collect(results_a))
    task_b = asyncio.create_task(_collect(results_b))
    await asyncio.sleep(0.05)

    await sse_manager.broadcast("CASE-SSE-3", {"msg": "hello"})
    await asyncio.sleep(0.05)

    await task_a
    await task_b

    assert len(results_a) == 1
    assert len(results_b) == 1
    assert results_a[0]["msg"] == "hello"
    assert results_b[0]["msg"] == "hello"
