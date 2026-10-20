"""Tests for the async SQLite database layer.

Verifies insert/read round-trips for audit_runs and traces,
and the complete_audit_run status transition.
"""

from __future__ import annotations

from app.services import database as db


async def test_init_db_creates_tables():
    """init_db should be idempotent and create both tables."""
    await db.init_db()
    # Calling twice should not raise
    await db.init_db()


async def test_insert_and_retrieve_audit_run():
    """Insert an audit run and verify it appears in get_runs."""
    await db.init_db()

    run_id = await db.insert_audit_run(
        case_id="CASE-001",
        doc_count=5,
        started_at="2026-01-01T00:00:00Z",
    )
    assert isinstance(run_id, int)
    assert run_id > 0

    runs = await db.get_runs()
    assert len(runs) == 1
    assert runs[0]["case_id"] == "CASE-001"
    assert runs[0]["doc_count"] == 5
    assert runs[0]["status"] == "running"


async def test_complete_audit_run():
    """complete_audit_run should flip status to 'completed'."""
    await db.init_db()

    await db.insert_audit_run(
        case_id="CASE-002",
        doc_count=3,
        started_at="2026-01-01T00:00:00Z",
    )
    await db.complete_audit_run(case_id="CASE-002", total_findings=7)

    runs = await db.get_runs()
    assert runs[0]["status"] == "completed"
    assert runs[0]["total_findings"] == 7
    assert runs[0]["ended_at"] is not None


async def test_insert_and_retrieve_trace():
    """Insert a trace row and verify it is returned by get_traces_for_case."""
    await db.init_db()

    run_id = await db.insert_audit_run(
        case_id="CASE-003",
        doc_count=1,
        started_at="2026-01-01T00:00:00Z",
    )

    trace_id = await db.insert_trace(
        run_id=run_id,
        case_id="CASE-003",
        event_type="agent_end",
        agent_name="compliance",
        decision_type="rule_check",
        detail="Checked 12 rules, 2 violations found.",
        findings_count=2,
        step_index=1,
        duration_ms=412.5,
        source_timestamp="2026-01-01T00:00:01Z",
        received_at="2026-01-01T00:00:02Z",
        raw_payload={"agent": "compliance", "findings_count": 2},
    )
    assert isinstance(trace_id, int)

    traces = await db.get_traces_for_case("CASE-003")
    assert len(traces) == 1
    assert traces[0]["agent_name"] == "compliance"
    assert traces[0]["findings_count"] == 2
    assert traces[0]["event_type"] == "agent_end"
    assert traces[0]["duration_ms"] == 412.5


async def test_get_traces_returns_empty_for_unknown_case():
    """Querying an unknown case_id should return an empty list."""
    await db.init_db()

    traces = await db.get_traces_for_case("NONEXISTENT")
    assert traces == []


async def test_traces_ordered_by_step_index():
    """Traces should be returned ordered by step_index ascending."""
    await db.init_db()

    run_id = await db.insert_audit_run(
        case_id="CASE-004",
        doc_count=2,
        started_at="2026-01-01T00:00:00Z",
    )

    # Insert in reverse order
    for step in [3, 1, 2]:
        await db.insert_trace(
            run_id=run_id,
            case_id="CASE-004",
            event_type="agent_end",
            agent_name=f"agent_{step}",
            decision_type=None,
            detail=None,
            findings_count=0,
            step_index=step,
            duration_ms=None,
            source_timestamp="2026-01-01T00:00:00Z",
            received_at="2026-01-01T00:00:00Z",
            raw_payload={},
        )

    traces = await db.get_traces_for_case("CASE-004")
    steps = [t["step_index"] for t in traces]
    assert steps == [1, 2, 3]
