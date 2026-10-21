"""Review Agent — Component 04's small AI agent.

Runs once an audit or a Copilot chat turn ends. Every review is saved in
MongoDB (``c04_reviews``, one per run); a run that already has one is never
reviewed again, so reading the same events twice costs no LLM call. It reads that run's trace (the same steps the
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
from app.services import report_store, review_store, sse_manager

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


# Room for the JSON answer, plus a little for a model that still thinks a bit first.
LLM_MAX_TOKENS = 500
_THINK = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL | re.IGNORECASE)

# Why a review fell back to the fixed summary (shown under the review, kept in c04_reviews).
UNREACHABLE = "unreachable"     # no reply from the server (down, timeout, HTTP error)
CUT_OFF = "cut_off"             # the reply hit the token limit before the answer
NO_ANSWER = "no_answer"         # a reply, but no summary in it
NOT_FAITHFUL = "not_faithful"   # a summary that used a number not in the facts


def _llm_request(prompt: str) -> tuple[str, dict, dict]:
    """(url, headers, body) for the configured LLM server."""
    messages = [{"role": "user", "content": prompt}]
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"} if config.LLM_API_KEY else {}
    if config.LLM_PROVIDER == "openai":
        url = config.LLM_API_URL.rstrip("/")
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"
        body = {"model": config.LLM_MODEL, "messages": messages, "temperature": 0,
                "max_tokens": LLM_MAX_TOKENS, "response_format": {"type": "json_object"}}
        if config.LLM_REASONING_EFFORT:
            body["reasoning_effort"] = config.LLM_REASONING_EFFORT
        return url, headers, body
    body = {"model": config.LLM_MODEL, "messages": messages, "stream": False,
            "format": "json", "options": {"temperature": 0, "num_predict": LLM_MAX_TOKENS}}
    if config.LLM_REASONING_EFFORT:
        body["think"] = config.LLM_REASONING_EFFORT != "none"  # Ollama's own switch
    return config.LLM_API_URL, headers, body


async def _call_llm(prompt: str) -> tuple[str | None, str | None]:
    """Ask the shared LLM for the summary: (summary, None), or (None, why it gave none)."""
    url, headers, body = _llm_request(prompt)
    try:
        async with httpx.AsyncClient(timeout=config.LLM_TIMEOUT) as client:
            resp = await client.post(url, json=body, headers=headers)
            if resp.status_code == 400 and "response_format" in body:
                # some OpenAI-compatible servers do not support JSON mode: ask again without it
                body = {k: v for k, v in body.items() if k != "response_format"}
                resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        if config.LLM_PROVIDER == "openai":
            choice = (data.get("choices") or [{}])[0]
            content = choice.get("message", {}).get("content") or ""
            finish = choice.get("finish_reason")
        else:
            content = data.get("message", {}).get("content") or ""
            finish = data.get("done_reason")
        content = _THINK.sub("", content).strip()  # some servers put the thinking inline
    except Exception as exc:  # noqa: BLE001 - any failure means: use the fixed summary
        logger.warning("Review agent: LLM unreachable (%s)", exc)
        return None, UNREACHABLE
    try:
        summary = str(json.loads(content).get("summary", "")).strip()
    except (json.JSONDecodeError, AttributeError):
        summary = "" if finish == "length" else content  # a cut-off JSON is not a summary
    if summary:
        return summary, None
    reason = CUT_OFF if finish == "length" else NO_ANSWER
    logger.warning("Review agent: LLM gave no summary (finish_reason=%s, %d chars of content)%s",
                   finish, len(content),
                   " - a thinking model? set C04_LLM_REASONING_EFFORT=none" if reason == CUT_OFF else "")
    return None, reason


# ── Public entry point ─────────────────────────────────────────────────

async def _publish(case_id: str, stream_id: str | None, payload: dict) -> None:
    await sse_manager.broadcast(case_id, payload)
    if stream_id and stream_id != case_id:
        await sse_manager.broadcast(stream_id, payload)


async def _saved(case_id: str, stream_id: str | None, run_key: str) -> dict | None:
    """A review already made for this run (e.g. the same events read again): stream it as it was."""
    try:
        saved = await review_store.get_review(run_key)
    except report_store.StoreUnavailable:
        return None
    if saved:
        await _publish(case_id, stream_id, saved)
    return saved


async def _deliver(case_id: str, stream_id: str | None, base: dict, verdict: str, headline: str,
                   next_steps: list[str], prompt: str, fallback: str) -> dict:
    """Explain + fallback, stream the finished review and save it in MongoDB."""
    summary, fallback_reason = await _call_llm(prompt)
    source = "ai"
    if summary is not None and not is_faithful(summary, prompt):
        logger.info("Review agent: LLM summary rejected (not faithful): %s", summary[:120])
        summary, fallback_reason = None, NOT_FAITHFUL
    if summary is None:
        summary, source = fallback, "rules"
    review = {
        **base, "event_type": "insight_summary", "stream_id": stream_id,
        "verdict": verdict, "headline": headline, "summary": summary,
        "next_steps": next_steps, "source": source, "fallback_reason": fallback_reason,
        "model": config.LLM_MODEL if source == "ai" else None,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    await _publish(case_id, stream_id, review)
    logger.info("Review  case=%s  kind=%s  verdict=%s  source=%s%s", case_id, base["run_kind"], verdict,
                source, f" ({fallback_reason})" if fallback_reason else "")
    try:
        await review_store.save_review(review)
    except report_store.StoreUnavailable:
        logger.warning("Review for %s could not be saved to MongoDB (shown live only)", base["run_key"])
    return review


async def review_run(case_id: str, run_key: str, total_findings: int,
                     status: str | None = None, stream_id: str | None = None) -> dict | None:
    """Review one finished audit run and stream the result. Never raises."""
    base = {"case_id": case_id, "run_key": run_key, "run_kind": "audit", "agent_name": AGENT_NAME}
    try:
        if saved := await _saved(case_id, stream_id, run_key):
            return saved
        await _publish(case_id, stream_id, {**base, "event_type": "insight_pending"})
        facts = observe(case_id, run_key, total_findings, status)
        verdict, headline, next_steps = decide(facts)
        return await _deliver(case_id, stream_id, base, verdict, headline, next_steps,
                              _prompt(facts, verdict, headline), fallback_summary(facts))
    except Exception:
        logger.exception("Review agent failed for case=%s — non-fatal", case_id)
        return None


# ── Copilot chats: the same four steps, chat-shaped ────────────────────

@dataclass
class TurnFacts:
    """What the trace of one Copilot turn shows."""
    question: str = ""
    goal: str = ""            # "explain why a finding was raised"
    recognised: str = ""      # "case ACME-1, rule CHK-001"
    lookups: int = 0
    lookup_errors: int = 0
    model_unavailable: bool = False
    failed: list[dict] = field(default_factory=list)
    answer: str = ""
    needs_input: bool = False


def observe_turn(stream_id: str, run_key: str, status: str | None) -> TurnFacts:
    events = [e for e in sse_manager.history(stream_id) if e.get("run_key") == run_key]
    f = TurnFacts(needs_input=status == "needs_slot")
    for e in events:
        kind = e.get("kind")
        if e.get("event_type") == "run_start":
            f.question = (e.get("detail") or "").strip()
        elif e.get("event_type") == "run_end":
            f.answer = " ".join((e.get("detail") or "").split())[:300]
        elif e.get("event_type") != "step":
            continue
        elif kind == "intent":
            f.goal = (e.get("detail") or "").removeprefix("you want to ").split(" · ")[0]
        elif kind == "entities":
            f.recognised = e.get("target") or ""
        elif kind == "kg_fetch":
            f.lookups += 1
            f.lookup_errors += e.get("tone") == "danger"
        elif kind == "llm_call":
            f.model_unavailable |= e.get("status") == "error"
        elif e.get("tone") == "danger":
            f.failed.append(e)
    return f


def decide_turn(f: TurnFacts) -> tuple[str, str, list[str]]:
    """(verdict, headline, next_steps) for a chat turn, from rules."""
    if f.failed:
        n = len(f.failed)
        steps = [f"Review {s.get('target', 'the check')} — {s.get('detail', '')}."
                 for s in f.failed[:MAX_STEPS]]
        return "action_required", f"{n} check{'s' if n != 1 else ''} failed — action needed", steps
    if f.needs_input:
        return "review", "Waiting for more details", ["Reply with the detail the assistant asked for."]
    steps = []
    if f.lookup_errors:
        steps.append("Some Knowledge Graph lookups failed; the answer may be incomplete. Ask again later.")
    if f.model_unavailable:
        steps.append("Keyword rules read the request because the language model could not be reached; "
                     "rephrase the question if the answer does not fit.")
    if steps:
        return "review", "Answered, with limited help", steps
    return "clear", "Answered", []


def fallback_turn(f: TurnFacts) -> str:
    text = f'You asked "{f.question}".' if f.question else "A question was asked."
    if f.goal:
        text += f" It was read as a request to {f.goal}"
        text += f", using {f.lookups} Knowledge Graph lookup(s)." if f.lookups else "."
    text += (" The assistant asked for more details." if f.needs_input
             else " The assistant answered.")
    return text


def _prompt_turn(f: TurnFacts, verdict: str, headline: str) -> str:
    facts = {"question": f.question, "understood_as": f.goal, "recognised": f.recognised,
             "knowledge_graph_lookups": f.lookups, "answer_start": f.answer,
             "asked_for_more_details": f.needs_input, "verdict": verdict, "headline": headline}
    return ("You are the Review Agent of an audit assistant. Using ONLY these facts, write a "
            "wrap-up of this chat turn in 1 or 2 short sentences (under 40 words): what the user "
            "asked and how the assistant answered. Do not invent numbers, names, laws or "
            "standards, and do not give advice.\n"
            f"Facts: {json.dumps(facts, ensure_ascii=False)}\n"
            'Reply as JSON: {"summary": "..."}')


async def review_turn(stream_id: str, run_key: str, status: str | None = None) -> dict | None:
    """Review one finished Copilot turn, stream and save the result. Never raises."""
    base = {"case_id": stream_id, "run_key": run_key, "run_kind": "copilot", "agent_name": AGENT_NAME}
    try:
        if saved := await _saved(stream_id, None, run_key):
            return saved
        await _publish(stream_id, None, {**base, "event_type": "insight_pending"})
        facts = observe_turn(stream_id, run_key, status)
        verdict, headline, next_steps = decide_turn(facts)
        return await _deliver(stream_id, None, base, verdict, headline, next_steps,
                              _prompt_turn(facts, verdict, headline), fallback_turn(facts))
    except Exception:
        logger.exception("Review agent failed for chat=%s — non-fatal", stream_id)
        return None
