"""The Review Agent: rules decide the verdict, the LLM only explains it."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app import config
from app.services import database as db
from app.services import review_agent, sse_manager, trace_reader

FIXTURE = Path(__file__).parent / "fixtures" / "c03_trace_events.json"
GENERAL_CHAT = "GEN-20261020-AB12"


@pytest.fixture(autouse=True)
async def _replayed():
    """Replay the recorded C03 events, without starting real reviews."""
    await db.init_db()
    for state in (trace_reader._last_seen, trace_reader._step_counters,
                  trace_reader._run_ids, sse_manager._history):
        state.clear()
    trace_reader._pending_rows.clear()
    with patch.object(trace_reader.review_agent, "review_run", AsyncMock()), \
            patch.object(trace_reader.review_agent, "review_turn", AsyncMock()):
        await trace_reader.process_batch(json.loads(FIXTURE.read_text(encoding="utf-8")))
    yield


def _run_key(case_id: str) -> str:
    return next(e["run_key"] for e in sse_manager.history(case_id)
                if e["event_type"] == "pipeline_start" and e["case_id"] == case_id)


def _llm(reply: str | None):
    return patch.object(review_agent, "_call_llm", AsyncMock(return_value=reply))


async def test_failed_checks_mean_action_needed_with_concrete_next_steps():
    facts = review_agent.observe("ACME-1", _run_key("ACME-1"), 3, "pending_auditor_review")
    verdict, headline, steps = review_agent.decide(facts)
    assert verdict == "action_required"
    assert headline.endswith("failed — action needed")
    assert any("CHK-001 on BS" in s for s in steps)
    assert steps[-1] == "Re-run the audit after the fixes."
    assert facts.documents == 3 and facts.agents[0] == "Data quality"


async def test_ai_summary_is_used_when_faithful():
    with _llm("The balance sheet does not balance and the receipt does not match its invoice."):
        review = await review_agent.review_run("ACME-1", _run_key("ACME-1"), 3)
    assert review["source"] == "ai" and review["verdict"] == "action_required"
    assert review["summary"].startswith("The balance sheet")
    events = [e["event_type"] for e in sse_manager.history("ACME-1") if e.get("agent_name") == "review_agent"]
    assert events == ["insight_pending", "insight_summary"]


async def test_invented_numbers_are_rejected_for_the_fixed_summary():
    with _llm("The audit found 97 problems worth Rs 4,200,000."):
        review = await review_agent.review_run("ACME-1", _run_key("ACME-1"), 3)
    assert review["source"] == "rules"
    assert "97" not in review["summary"]
    assert review["summary"].endswith("The audit raised 3 finding(s).")


async def test_offline_model_still_gets_a_review():
    with _llm(None):
        review = await review_agent.review_run("ACME-1", _run_key("ACME-1"), 3)
    assert review["source"] == "rules" and review["model"] is None
    assert "checked 3 document(s)" in review["summary"]


async def test_review_of_an_audit_started_from_a_chat_reaches_that_chat():
    with _llm(None):
        await review_agent.review_run("NEW-1", _run_key("NEW-1"), 1, stream_id=GENERAL_CHAT)
    assert any(e["event_type"] == "insight_summary" for e in sse_manager.history(GENERAL_CHAT))


async def test_reviews_are_saved_in_mongodb_and_never_made_twice(_in_memory_mongo):
    key = _run_key("ACME-1")
    with _llm("The balance sheet does not balance.") as first:
        made = await review_agent.review_run("ACME-1", key, 3)
    saved = _in_memory_mongo[config.REVIEWS_COLLECTION].find_one({"_id": key})
    assert (saved["verdict"], saved["summary"], saved["run_kind"]) == (
        "action_required", "The balance sheet does not balance.", "audit")
    assert first.await_count == 1

    # the same run reviewed again (e.g. its events read again after a restart): no LLM call
    with _llm("A different text.") as second:
        again = await review_agent.review_run("ACME-1", key, 3)
    assert second.await_count == 0
    assert again["summary"] == made["summary"]


async def test_chat_reviews_are_saved_too(_in_memory_mongo):
    key = _turn_key("ACME-1")
    with _llm(None):
        await review_agent.review_turn("ACME-1", key, "done")
    assert _in_memory_mongo[config.REVIEWS_COLLECTION].find_one({"_id": key})["run_kind"] == "copilot"


def test_openai_compatible_server_request(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(config, "LLM_API_URL", "https://gpu-pod.example/v1")
    monkeypatch.setattr(config, "LLM_MODEL", "qwen2.5-14b-instruct")
    monkeypatch.setattr(config, "LLM_API_KEY", "k")
    url, headers, body = review_agent._llm_request("facts")
    assert url == "https://gpu-pod.example/v1/chat/completions"
    assert headers == {"Authorization": "Bearer k"}
    assert body["model"] == "qwen2.5-14b-instruct" and body["messages"][0]["content"] == "facts"


def test_clean_run_is_all_clear():
    facts = review_agent.RunFacts(case_id="C", version=1, status="pending_auditor_review",
                                  total_findings=0, documents=2, passed=9)
    assert review_agent.decide(facts)[:2] == ("clear", "All checks passed")


def test_not_auditable_case():
    facts = review_agent.RunFacts(case_id="C", version=1, status="not_auditable", total_findings=1)
    assert review_agent.decide(facts)[0] == "action_required"


def test_faithfulness_check():
    prompt = 'Facts: {"checks_passed": 9, "findings_raised": 2}'
    assert review_agent.is_faithful("9 checks passed and 2 findings were raised.", prompt)
    assert not review_agent.is_faithful("12 findings were raised.", prompt)
    assert not review_agent.is_faithful("", prompt)
    assert not review_agent.is_faithful("x" * 400, prompt)


# --- Copilot chat turns ---------------------------------------------------------------

def _turn_key(stream: str) -> str:
    return next(e["run_key"] for e in sse_manager.history(stream) if e["event_type"] == "run_start")


async def test_an_answered_chat_turn_gets_a_wrap_up():
    with _llm("You asked why CHK-001 failed on case ACME-1 and the assistant explained the finding."):
        review = await review_agent.review_turn("ACME-1", _turn_key("ACME-1"), "done")
    assert (review["run_kind"], review["verdict"], review["headline"]) == ("copilot", "clear", "Answered")
    assert review["source"] == "ai" and review["next_steps"] == []
    turn = [e["event_type"] for e in sse_manager.history("ACME-1")
            if e.get("run_key") == review["run_key"] and e.get("agent_name") == "review_agent"]
    assert turn == ["insight_pending", "insight_summary"]


async def test_chat_wrap_up_without_the_model_reads_the_trace():
    with _llm(None):
        review = await review_agent.review_turn("ACME-1", _turn_key("ACME-1"), "done")
    assert review["source"] == "rules"
    assert review["summary"].startswith('You asked "why did CHK-001 fail on case ACME-1?".')
    assert "explain why a finding was raised" in review["summary"]


def test_chat_verdicts():
    asked = review_agent.TurnFacts(question="add this", needs_input=True)
    assert review_agent.decide_turn(asked)[:2] == ("review", "Waiting for more details")
    offline = review_agent.TurnFacts(question="hey", model_unavailable=True)
    verdict, headline, steps = review_agent.decide_turn(offline)
    assert (verdict, headline) == ("review", "Answered, with limited help")
    assert "language model could not be reached" in steps[0]
    failed = review_agent.TurnFacts(failed=[{"target": "CHK-004 on TXN", "detail": "cash out with no asset in"}])
    assert review_agent.decide_turn(failed)[0] == "action_required"
