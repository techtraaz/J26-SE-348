"""Smart Insight Generator — the AI Meta-Agent of Component 04.

Triggered automatically when the trace reader receives a ``pipeline_end``
event.  It decides whether the completed audit was complex enough to
warrant an LLM-generated diagnostic summary, and if so, calls the shared
LLM instance and pushes the result to SSE as an ``insight_summary``
event.

Smart Filter Logic (avoids spamming simple audits):
  - Count of ``chain_end`` trace rows for the case.
  - Total findings reported in ``pipeline_end``.
  - If the audit is trivial (few agents, zero findings), abort silently.
  - If it's complex, build a structured prompt from the trace data and
    ask the LLM for a 1–2 sentence diagnostic summary.

Design:
  - Runs as a fire-and-forget ``asyncio.create_task`` so the trace reader
    is never blocked waiting for the LLM.
  - If the LLM is offline, catches the exception and logs a warning —
    the audit pipeline is never affected.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx

from app import config
from app.services import database as db
from app.services import sse_manager

logger = logging.getLogger("c04.insight")


# ── Smart Filter ───────────────────────────────────────────────────────

def _should_generate(traces: list[dict], total_findings: int) -> bool:
    """Decide whether this audit is complex enough to justify an insight.

    Returns False (skip) for simple, fast, zero-finding audits.
    Returns True when the audit involved enough agents and findings
    to make a diagnostic summary valuable.
    """
    agent_steps = [t for t in traces if t.get("event_type") in ("agent_end", "chain_end")]
    agent_count = len(agent_steps)

    # Check for error keywords in any trace detail
    has_errors = any(
        "error" in (t.get("detail") or "").lower()
        or "fail" in (t.get("detail") or "").lower()
        or "broken" in (t.get("detail") or "").lower()
        for t in traces
    )

    # Complex enough? — multiple agents OR findings exist OR errors detected
    if has_errors:
        return True
    if agent_count >= config.INSIGHT_MIN_AGENTS and total_findings >= config.INSIGHT_MIN_FINDINGS:
        return True

    logger.info(
        "Insight skipped (simple audit): agents=%d  findings=%d",
        agent_count, total_findings,
    )
    return False


# ── LLM Prompt Builder ────────────────────────────────────────────────

def _build_prompt(case_id: str, traces: list[dict], total_findings: int) -> str:
    """Build a structured prompt for the LLM from trace data."""
    agent_lines = []
    for t in traces:
        if t.get("event_type") in ("agent_end", "chain_end"):
            name = t.get("agent_name", "unknown")
            detail = t.get("detail", "no detail")
            findings = t.get("findings_count", 0)
            duration = t.get("duration_ms")
            dur_str = f", took {duration:.0f}ms" if duration else ""
            agent_lines.append(f"  - {name}: {detail} (findings: {findings}{dur_str})")
        elif t.get("event_type") in ("chain_error", "agent_error"):
            name = t.get("agent_name", "unknown")
            error = t.get("detail") or t.get("error", "unknown error")
            agent_lines.append(f"  - {name}: ERROR — {error}")

    agent_summary = "\n".join(agent_lines) if agent_lines else "  (no agent traces)"

    return (
        f"You are an expert internal auditor reviewing the execution trace of an "
        f"automated multi-agent audit system.\n\n"
        f"Case ID: {case_id}\n"
        f"Total findings: {total_findings}\n"
        f"Agent execution trace:\n{agent_summary}\n\n"
        f"Provide a brief 1-2 sentence diagnostic summary of this audit run. "
        f"Focus on what was checked, what issues were found, and whether the "
        f"auditor should pay close attention to any specific area. "
        f"Be concise and professional."
    )


# ── LLM Call ───────────────────────────────────────────────────────────

async def _call_llm(prompt: str) -> str | None:
    """Call the shared Ollama instance. Returns the response text or None on failure."""
    try:
        async with httpx.AsyncClient(timeout=config.LLM_TIMEOUT) as client:
            resp = await client.post(
                config.LLM_API_URL,
                json={
                    "model": config.LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = data.get("message", {}).get("content", "").strip()
            return text if text else None
    except httpx.TimeoutException:
        logger.warning("LLM call timed out after %ds", config.LLM_TIMEOUT)
        return None
    except Exception:
        logger.warning("LLM call failed — LLM may be offline", exc_info=True)
        return None


# ── Public Entry Point ─────────────────────────────────────────────────

async def maybe_generate_insight(case_id: str, total_findings: int) -> None:
    """Evaluate and optionally generate an AI insight summary for a completed audit.

    Called as a fire-and-forget task from the trace reader's pipeline_end
    handler.  Safe to fail — never crashes, never blocks the main flow.
    """
    try:
        # 1. Fetch all traces for this case from the Middle DB
        traces = await db.get_traces_for_case(case_id)

        # 2. Smart Filter — should we bother the LLM?
        if not _should_generate(traces, total_findings):
            return

        # 3. Build prompt and call LLM
        prompt = _build_prompt(case_id, traces, total_findings)
        logger.info("Generating insight for case=%s  (findings=%d)", case_id, total_findings)

        summary = await _call_llm(prompt)
        if not summary:
            logger.info("No insight generated for case=%s (LLM returned empty/unavailable)", case_id)
            return

        # 4. Push to SSE as a special event
        now = datetime.now(timezone.utc).isoformat()
        await sse_manager.broadcast(case_id, {
            "event_type": "insight_summary",
            "case_id": case_id,
            "summary": summary,
            "generated_at": now,
        })
        logger.info("✦ Insight delivered  case=%s  summary=%s", case_id, summary[:80])

    except Exception:
        # Never let the insight generator crash anything
        logger.exception("Insight generation failed for case=%s — non-fatal", case_id)
