"""The trace reader turns real C03 events into the live Thinking stream.

Replays a fixture recorded from C03 (one audit, a Copilot question about it,
and a Copilot turn in a general chat that ran an audit of another case).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.services import database as db
from app.services import sse_manager, trace_reader

FIXTURE = Path(__file__).parent / "fixtures" / "c03_trace_events.json"
GENERAL_CHAT = "GEN-20261020-AB12"


@pytest.fixture(autouse=True)
async def _fresh_state():
    await db.init_db()
    for state in (trace_reader._last_seen, trace_reader._step_counters,
                  trace_reader._run_ids, sse_manager._history):
        state.clear()
    trace_reader._pending_rows.clear()
    with patch.object(trace_reader.review_agent, "review_run", AsyncMock()), \
            patch.object(trace_reader.review_agent, "review_turn", AsyncMock()):
        yield


def _events() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


async def test_audit_stream_has_stages_steps_and_end():
    await trace_reader.process_batch(_events())
    acme = [p for p in sse_manager.history("ACME-1") if p["run_kind"] == "audit"]
    types = [p["event_type"] for p in acme]
    assert types[0] == "pipeline_start" and types[-1] == "pipeline_end"
    stages = [p["stage"] for p in acme if p["event_type"] == "agent_thinking"]
    assert sorted(stages) == ["anomaly", "compliance", "data_quality",
                              "evidence_validation", "reasoning"]
    assert len({p["run_key"] for p in acme}) == 1  # one run
    failed = [p for p in acme if p["event_type"] == "step" and p["status"] == "failed"]
    chk1 = next(p for p in failed if p["target"] == "CHK-001 on BS")
    assert chk1["stage"] == "compliance" and chk1["tone"] == "danger"
    assert "Assets 100 ≠ Liabilities + Capital 50" in chk1["detail"]
    done = next(p for p in acme if p["event_type"] == "agent_done" and p["stage"] == "compliance")
    assert done["label"] == "Compliance" and done["detail"].startswith("Compliance ran")


async def test_copilot_turn_is_its_own_run_on_the_same_stream():
    await trace_reader.process_batch(_events())
    turn = [p for p in sse_manager.history("ACME-1") if p["run_kind"] == "copilot"]
    types = [p["event_type"] for p in turn]
    assert types[0] == "run_start" and types[-1] == "run_end"
    assert {p["stage"] for p in turn if p["event_type"] == "agent_thinking"} == {
        "copilot_nlu", "copilot"}
    intent = next(p for p in turn if p["event_type"] == "step" and p["kind"] == "intent")
    assert intent["verb"] == "Understood"


async def test_audit_started_from_a_chat_is_shown_on_that_chat():
    await trace_reader.process_batch(_events())
    chat = sse_manager.history(GENERAL_CHAT)
    kinds = {(p["run_kind"], p["case_id"]) for p in chat}
    assert kinds == {("copilot", GENERAL_CHAT), ("audit", "NEW-1")}
    assert any(p["event_type"] == "pipeline_start" and p["case_id"] == "NEW-1" for p in chat)


async def test_steps_are_persisted_and_events_are_not_processed_twice():
    events = _events()
    first = await trace_reader.process_batch(events)
    assert first == len(events)
    assert await trace_reader.process_batch(events) == 0
    rows = await db.get_traces_for_case("ACME-1")
    steps = [r for r in rows if r["event_type"] == "step"]
    assert len(steps) == sum(1 for e in events if e["event_type"] == "step"
                             and e["case_id"] == "ACME-1")
    assert all(s["run_id"] for s in steps if s["agent_name"] != "copilot_nlu")


async def test_a_new_run_of_the_same_case_is_not_mistaken_for_a_replay():
    events = [e for e in _events() if e["case_id"] == "ACME-1" and e["run_kind"] == "audit"]
    await trace_reader.process_batch(events)
    rerun = [{**e, "trace_id": "second-run", "version": 2} for e in events]
    assert await trace_reader.process_batch(rerun) == len(rerun)


async def test_replay_reaches_a_client_that_connects_late():
    await trace_reader.process_batch(_events())
    got = []
    async for payload in sse_manager.subscribe("ACME-1"):
        got.append(payload)
        if len(got) == len(sse_manager.history("ACME-1")):
            break
    assert got == sse_manager.history("ACME-1")


async def test_copilot_steps_in_the_same_batch_do_not_drop_audit_steps():
    events = _events()
    chat = [e for e in events if e["case_id"] == GENERAL_CHAT and e["event_type"] == "step"]
    audit = [e for e in events if e["case_id"] == "ACME-1" and e["run_kind"] == "audit"]
    end = next(i for i, e in enumerate(audit) if e["event_type"] == "pipeline_end")
    # one poll that mixes a Copilot step (no audit run) into an audit's steps
    await trace_reader.process_batch(audit[:end] + chat[:1] + audit[end:])
    rows = await db.get_traces_for_case("ACME-1")
    assert sum(r["event_type"] == "step" for r in rows) == sum(
        e["event_type"] == "step" for e in audit)


async def test_every_finished_chat_turn_is_sent_to_the_review_agent():
    for state in (trace_reader._last_seen, trace_reader._step_counters, sse_manager._history):
        state.clear()
    with patch.object(trace_reader.review_agent, "review_turn", AsyncMock()) as review_turn:
        await trace_reader.process_batch(_events())
    turns = [e for e in _events() if e["event_type"] == "copilot_end"]
    assert review_turn.await_count == len(turns) == 2
    assert {c.args[0] for c in review_turn.await_args_list} == {"ACME-1", GENERAL_CHAT}
