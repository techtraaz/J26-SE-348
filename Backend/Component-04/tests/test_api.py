"""Tests for the FastAPI endpoints.

Uses httpx.AsyncClient with the ASGI transport to test endpoints
without starting a real server or needing Redis/LLM running.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx

from app.main import app
from app.services import database as db


async def test_health_endpoint():
    """GET /health should return 200 with ok=True."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "component-04" in body["service"]


async def test_runs_endpoint_empty():
    """GET /runs should return 200 with an empty list when no data exists."""
    await db.init_db()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/runs")

    assert resp.status_code == 200
    body = resp.json()
    assert body["runs"] == []


async def test_runs_endpoint_with_data():
    """GET /runs should return inserted audit runs."""
    await db.init_db()
    await db.insert_audit_run(case_id="API-CASE-1", doc_count=3, started_at="2026-01-01T00:00:00Z")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/runs")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["runs"]) == 1
    assert body["runs"][0]["case_id"] == "API-CASE-1"


async def test_traces_endpoint_returns_traces():
    """GET /traces/{case_id} should return stored traces."""
    await db.init_db()
    run_id = await db.insert_audit_run(case_id="API-CASE-2", doc_count=1, started_at="2026-01-01T00:00:00Z")
    await db.insert_trace(
        run_id=run_id,
        case_id="API-CASE-2",
        event_type="agent_end",
        agent_name="anomaly",
        decision_type="detection",
        detail="Found 1 anomaly",
        findings_count=1,
        step_index=1,
        source_timestamp="2026-01-01T00:00:01Z",
        received_at="2026-01-01T00:00:02Z",
        raw_payload={"agent": "anomaly"},
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/traces/API-CASE-2")

    assert resp.status_code == 200
    body = resp.json()
    assert body["case_id"] == "API-CASE-2"
    assert body["trace_count"] == 1
    assert body["traces"][0]["agent_name"] == "anomaly"


async def test_traces_endpoint_unknown_case():
    """GET /traces/{case_id} for a nonexistent case should return empty list."""
    await db.init_db()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/traces/NONEXISTENT")

    assert resp.status_code == 200
    body = resp.json()
    assert body["trace_count"] == 0
    assert body["traces"] == []


async def test_report_generate_404_for_unknown_case():
    """POST /report/generate/{case_id} should 404 when no audit data exists."""
    await db.init_db()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/report/generate/NONEXISTENT")

    assert resp.status_code == 404


async def test_report_download_404_for_missing_file():
    """GET /report/download/{filename} should 404 for a nonexistent file."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/report/download/does_not_exist.pdf")

    assert resp.status_code == 404
