"""Review Agent — Component 04's small AI agent.

Runs once an audit ends. It reads that run's trace (the same steps the
Thinking timeline shows) and writes a short review at the bottom of the
run: a verdict, a two-sentence summary and the next steps.

Like the agents in Component 03, the decision is not left to the LLM:

  1. Observe   collect the run's steps from the live stream history.
  2. Decide    the verdict and next steps come from rules over those steps
               (failed checks -> action needed; items to confirm -> needs
               confirmation; otherwise all clear).
  3. Explain   the LLM writes the two-sentence summary from those facts.
               A reply that is empty, too long, or uses a number that is
               not in the facts is rejected.
  4. Fallback  if the LLM is offline or rejected, a fixed-wording summary
               is used, so a review always appears.

It is fire-and-forget (``asyncio.create_task``): the trace reader never
waits for it, and any failure is logged, never raised.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from app import config
from app.services import database as db
from app.services import sse_manager

logger = logging.getLogger("c04.review_agent")

AGENT_NAME = "review_agent"
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_MAX_SUMMARY = 360
MAX_STEPS = 4  # next steps shown under a review


# ── 1. Observe ─────────────────────────────────────────────────────────

@dataclass
class RunFacts:
    """What the trace of one run shows."""
    case_id: str
    version: int | None
    status: str | None
    total_findings: int
    agents: list[str] = field(default_factory=list)
    documents: int = 0
    passed: int = 0
    failed: list[dict] = field(default_factory=list)      # red rows
    to_confirm: list[dict] = field(default_factory=list)  # amber rows (not model issues)
    skipped: list[dict] = field(default_factory=list)
    agent_errors: list[str] = field(default_factory=list)
    model_unavailable: bool = False
    kg_offline: bool = False

    @property
    def checks(self) -> int:
        return self.passed + len(self.failed) + len(self.skipped)


def _fact(step: dict, label: str) -> str:
    return next((f["value"] for f in step.get("facts") or [] if f.get("label") == label), "")


def observe(case_id: str, run_key: str, total_findings: int, status: str | None) -> RunFacts:
    events = [e for e in sse_manager.history(case_id) if e.get("run_key") == run_key]
    steps = [e for e in events if e.get("event_type") == "step"]
    facts = RunFacts(
        case_id=case_id,
        version=next((e.get("version") for e in events if e.get("version")), None),
        status=status,
        total_findings=total_findings,
        agents=list(dict.fromkeys(e["label"] for e in events
                                  if e.get("event_type") == "agent_done" and e.get("label"))),
        documents=sum(1 for s in steps if s.get("kind") == "evidence_read"),
        passed=sum(1 for s in steps if s.get("check") and s.get("status") == "passed"),
        agent_errors=[e.get("detail") or "" for e in events if e.get("event_type") == "agent_error"],
    )
    for s in steps:
        if s.get("kind") == "llm_call":
            facts.model_unavailable |= s.get("status") == "error"
            continue
        if s.get("kind") == "kg_fetch" and "offline" in _fact(s, "Source"):
            facts.kg_offline = True
        if s.get("tone") == "danger":
            facts.failed.append(s)
        elif s.get("tone") == "warning":
            facts.to_confirm.append(s)
        elif s.get("status") == "skipped" and s.get("kind") == "rule_check":
            facts.skipped.append(s)
    return facts


# ── 2. Decide ──────────────────────────────────────────────────────────

def _row(step: dict) -> str:
    return f"{step.get('verb', '')} {step.get('target', '')}".strip()


def decide(f: RunFacts) -> tuple[str, str, list[str]]:
    """(verdict, headline, next_steps) from rules; the LLM never decides these."""
    steps: list[str] = []
    if f.status == "not_auditable":
        return ("action_required", "The case could not be audited",
                ["Fix the rejected documents shown under Data quality, then re-run the audit."])
    if f.agent_errors:
        steps.append("An agent stopped with an error; re-run the audit once it is resolved.")
    for s in f.failed[:3]:
        if s.get("kind") == "evidence_link":
            steps.append(f"Add the missing evidence for {s.get('target', '').removeprefix('for ')} "
                         f"({s.get('detail', '')}).")
        elif s.get("kind") == "citation_check":
            steps.append(f"Check the {s.get('target', 'citations')}: {s.get('detail', '')}.")
        else:
            steps.append(f"Resolve {s.get('target', 'the failed check')} — {s.get('detail', '')}.")
    if len(f.failed) > 3:
        steps.append(f"Review the other {len(f.failed) - 3} failed check(s) in the timeline above.")
    for s in f.to_confirm[:2]:
        steps.append(f"Confirm {s.get('target', 'the item')}: {s.get('detail', '')}.")
    if f.skipped:
        steps.append(f"Supply the missing values for {len(f.skipped)} skipped check(s) "
                     f"so they can run.")
    if f.kg_offline:
        steps.append("Re-run when the live Knowledge Graph is reachable (an offline rule set was used).")

    if f.agent_errors or f.failed:
        n = len(f.failed)
        head = f"{n} check{'s' if n != 1 else ''} failed — action needed" if n else "Action needed"
        return "action_required", head, steps[:MAX_STEPS - 1] + ["Re-run the audit after the fixes."]
    if f.to_confirm or f.skipped or f.kg_offline:
        return "review", "Passed, with items to confirm", steps[:MAX_STEPS]
    return "clear", "All checks passed", ["No action needed; the findings can go to the auditor for sign-off."]


# ── 3. Explain ─────────────────────────────────────────────────────────

def fallback_summary(f: RunFacts) -> str:
    agents = ", ".join(f.agents) if f.agents else "the audit agents"
    parts = [f"{f.passed} passed"]
    if f.failed:
        parts.append(f"{len(f.failed)} failed")
    if f.skipped:
        parts.append(f"{len(f.skipped)} skipped")
    text = (f"{agents} checked {f.documents} document(s) in {f.checks} check(s): "
            f"{', '.join(parts)}.")
    if f.to_confirm:
        text += f" {len(f.to_confirm)} item(s) need confirmation."
    return f"{text} The audit raised {f.total_findings} finding(s)."


def _prompt(f: RunFacts, verdict: str, headline: str) -> str:
    facts = {
        "case": f.case_id, "version": f.version, "verdict": verdict, "headline": headline,
        "documents_read": f.documents, "checks_passed": f.passed,
        "failed": [f"{_row(s)}: {s.get('detail', '')}" for s in f.failed[:6]],
        "to_confirm": [f"{_row(s)}: {s.get('detail', '')}" for s in f.to_confirm[:4]],
        "skipped_checks": len(f.skipped), "findings_raised": f.total_findings,
        "agents": f.agents, "offline_rule_set": f.kg_offline,
    }
    return ("You are the Review Agent of an automated audit system. Using ONLY these facts, "
            "write a summary for the auditor in at most 2 short sentences (under 45 words): "
            "what the audit found and why it matters. Name checks and documents exactly as "
            "they are written in the facts and do not guess what a document or rule is about. "
            "Do not invent numbers, names, laws or standards, and do not give the next steps "
            "(they are listed separately).\n"
            f"Facts: {json.dumps(facts)}\n"
            'Reply as JSON: {"summary": "..."}')


def is_faithful(text: str, prompt: str) -> bool:
    """Short, not empty, and every number in it appears in the facts."""
    t = text.strip()
    if not t or len(t) > _MAX_SUMMARY:
        return False
    given = {n.replace(",", "") for n in _NUMBER.findall(prompt)}
    return all(n.replace(",", "") in given for n in _NUMBER.findall(t))


async def _call_llm(prompt: str) -> str | None:
    """Ask the shared LLM (Ollama /api/chat). None when it is unavailable."""
    try:
        async with httpx.AsyncClient(timeout=config.LLM_TIMEOUT) as client:
            resp = await client.post(config.LLM_API_URL, json={
                "model": config.LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
            })
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content", "").strip()
    except Exception as exc:  # noqa: BLE001 - any failure means: use the fixed summary
        logger.warning("Review agent: LLM unavailable (%s)", exc)
        return None
    try:
        return str(json.loads(content).get("summary", "")).strip() or None
    except (json.JSONDecodeError, AttributeError):
        return content or None


# ── Public entry point ─────────────────────────────────────────────────

async def _publish(case_id: str, stream_id: str | None, payload: dict) -> None:
    await sse_manager.broadcast(case_id, payload)
    if stream_id and stream_id != case_id:
        await sse_manager.broadcast(stream_id, payload)


async def review_run(case_id: str, run_key: str, total_findings: int,
                     status: str | None = None, stream_id: str | None = None) -> dict | None:
    """Review one finished audit run and stream the result. Never raises."""
    base = {"case_id": case_id, "run_key": run_key, "run_kind": "audit", "agent_name": AGENT_NAME}
    try:
        await _publish(case_id, stream_id, {**base, "event_type": "insight_pending"})
        facts = observe(case_id, run_key, total_findings, status)
        verdict, headline, next_steps = decide(facts)
        prompt = _prompt(facts, verdict, headline)
        summary = await _call_llm(prompt)
        source = "ai"
        if summary is None or not is_faithful(summary, prompt):
            if summary is not None:
                logger.info("Review agent: LLM summary rejected (not faithful): %s", summary[:120])
            summary, source = fallback_summary(facts), "rules"
        review = {
            **base, "event_type": "insight_summary",
            "verdict": verdict, "headline": headline, "summary": summary,
            "next_steps": next_steps, "source": source,
            "model": config.LLM_MODEL if source == "ai" else None,
            "generated_at": datetime.now(UTC).isoformat(),
        }
        await _publish(case_id, stream_id, review)
        logger.info("✦ Review  case=%s  verdict=%s  source=%s", case_id, verdict, source)
        await _persist(case_id, review)
        return review
    except Exception:
        logger.exception("Review agent failed for case=%s — non-fatal", case_id)
        return None


async def _persist(case_id: str, review: dict) -> None:
    """Keep the review with the run's traces (for the PDF report). Non-fatal."""
    try:
        run = await db.get_latest_run(case_id)
        now = review["generated_at"]
        await db.insert_trace(
            run_id=run["id"] if run else 0, case_id=case_id, event_type="ai_review",
            agent_name=AGENT_NAME, decision_type=review["verdict"],
            detail=f"{review['headline']}. {review['summary']}", findings_count=None,
            step_index=0, duration_ms=None, source_timestamp=now, received_at=now,
            raw_payload=review)
    except Exception:
        logger.debug("Review could not be saved (non-fatal)", exc_info=True)
