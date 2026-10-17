"""Tests for the Insight Generator smart filter logic.

Verifies the _should_generate function correctly distinguishes simple
audits (skip) from complex audits (generate) without needing a real LLM.
"""

from __future__ import annotations

from app.services.insight_generator import _should_generate


def test_empty_traces_zero_findings_skips():
    """No traces and zero findings → simple audit → skip."""
    assert _should_generate([], 0) is False


def test_single_agent_zero_findings_skips():
    """One agent, zero findings → simple audit → skip."""
    traces = [
        {"event_type": "pipeline_start", "detail": "Started"},
        {"event_type": "agent_end", "detail": "All good", "agent_name": "compliance"},
        {"event_type": "pipeline_end", "detail": "Done"},
    ]
    assert _should_generate(traces, 0) is False


def test_single_agent_with_findings_skips():
    """One agent but with findings → below MIN_AGENTS threshold → skip."""
    traces = [
        {"event_type": "agent_end", "detail": "Found issues", "agent_name": "compliance"},
    ]
    # 1 agent < MIN_AGENTS(2), even with findings
    assert _should_generate(traces, 3) is False


def test_multiple_agents_with_findings_generates():
    """Multiple agents and findings → complex audit → generate insight."""
    traces = [
        {"event_type": "agent_end", "detail": "Checked quality", "agent_name": "data_quality"},
        {"event_type": "agent_end", "detail": "Checked compliance", "agent_name": "compliance"},
        {"event_type": "agent_end", "detail": "Anomalies found", "agent_name": "anomaly"},
    ]
    assert _should_generate(traces, 5) is True


def test_error_in_trace_always_generates():
    """Traces containing error keywords → always generate, even with 1 agent."""
    traces = [
        {"event_type": "agent_end", "detail": "Error during processing", "agent_name": "reasoning"},
    ]
    assert _should_generate(traces, 0) is True


def test_failure_keyword_triggers_generation():
    """The word 'fail' in a trace detail should trigger generation."""
    traces = [
        {"event_type": "agent_end", "detail": "Validation failed for row 7", "agent_name": "data_quality"},
    ]
    assert _should_generate(traces, 0) is True


def test_broken_keyword_triggers_generation():
    """The word 'broken' in a trace detail should trigger generation."""
    traces = [
        {"event_type": "pipeline_start", "detail": "Broken data pipeline detected"},
    ]
    assert _should_generate(traces, 0) is True


def test_non_agent_events_not_counted():
    """Only agent_end events count toward the agent threshold."""
    traces = [
        {"event_type": "pipeline_start", "detail": "Started"},
        {"event_type": "pipeline_end", "detail": "Ended"},
    ]
    # 0 agent_end events, so even with findings, doesn't meet threshold
    assert _should_generate(traces, 5) is False


def test_multiple_agents_zero_findings_skips():
    """Multiple agents but zero findings → doesn't meet BOTH conditions → skip."""
    traces = [
        {"event_type": "agent_end", "detail": "All clear", "agent_name": "data_quality"},
        {"event_type": "agent_end", "detail": "All clear", "agent_name": "compliance"},
        {"event_type": "agent_end", "detail": "All clear", "agent_name": "anomaly"},
    ]
    assert _should_generate(traces, 0) is False
