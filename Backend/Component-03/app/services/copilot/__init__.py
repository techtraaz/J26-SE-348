"""Audit Copilot: natural-language requests over audits, rules and standards.

    text -> entities (code) -> intent (LLM, rules fallback) -> slot check -> handler

Intents live in handlers.py (registry in registry.py). Replies are built in
code from saved results and KG data.
"""
from app.schemas.chat import SessionContext
from app.schemas.copilot import CopilotQuery, CopilotResponse
from app.services import intake
from app.services.copilot import handlers  # noqa: F401 - registers the intents
from app.services.copilot import memory as memory_rules
from app.services.copilot.entities import Entities, extract
from app.services.copilot.handlers import Turn
from app.services.copilot.nlu import RequestContext, understand
from app.services.copilot.registry import NEEDS, REGISTRY
from app.services.kg_client import KGClient, KGError, default_kg
from app.services.store import ResultStore, default_store

__all__ = ["RequestContext", "answer", "extract", "understand"]


def _missing(need: str, turn: Turn) -> str | None:
    if need == "case" and not turn.case_id:
        return NEEDS["case"]
    if need == "saved_case":
        if not turn.case_id:
            return NEEDS["saved_case"]
        if turn.record() is None:
            return f"Case {turn.case_id} has no saved audit yet. Run a fresh audit first."
    if need == "docs" and not turn.query.docs:
        return NEEDS["docs"]
    if need == "rule" and not turn.entities.rule_ids:
        return NEEDS["rule"]
    if need == "doc_type" and not turn.entities.doc_types:
        return NEEDS["doc_type"]
    if need == "text_values" and not turn.entities.amounts:
        return NEEDS["text_values"]
    return None


def _entities(q: CopilotQuery, store: ResultStore,
              memory: SessionContext | None) -> tuple[Entities, str | None]:
    """Extract entities and pick the case: one named in the text, else the
    request's case, else a known case id written in the text, else the case the
    conversation was about. Follow-ups are then filled from memory."""
    ent = extract(q.text)
    case_id = ent.case_ids[0] if ent.case_ids else q.case_id
    if case_id is None:
        known = [r["case_id"] for r in store.latest_all()]
        ent = extract(q.text, known_case_ids=known)
        case_id = ent.case_ids[0] if ent.case_ids else (memory.case_id if memory else None)
    latest = store.latest(case_id) if case_id else None
    if latest:
        docs = [d["doc_id"] for d in latest["case"]["docs"]]
        ent.doc_ids = extract(q.text, known_doc_ids=docs).doc_ids
    same_case = memory is not None and memory.case_id == case_id
    return memory_rules.apply(ent, q.text, memory if same_case else None), case_id


# ── Copilot XAI tracing (fire-and-forget, same collection as orchestrator) ──

import logging
import time
from datetime import UTC, datetime

_xai_log = logging.getLogger("c03.copilot.xai")
_copilot_seq = 0


def _copilot_emit(store: ResultStore, event: dict) -> None:
    """Write one trace doc to c03_callback_traces. Swallows ALL errors."""
    global _copilot_seq
    _copilot_seq += 1
    event["seq"] = _copilot_seq
    try:
        col = store.traces_collection()
        if col is not None:
            col.insert_one(event)
    except Exception:  # noqa: BLE001
        _xai_log.debug("Copilot trace write skipped (non-fatal)", exc_info=True)


def answer(q: CopilotQuery, kg: KGClient | None = None, store: ResultStore | None = None,
           memory: SessionContext | None = None) -> CopilotResponse:
    """One request. `memory` (a chat session's context) lets follow-ups such as
    "why did that one fire?" resolve; without it every request stands alone."""
    kg = kg or default_kg()
    store = store or default_store()
    t0 = time.perf_counter()
    ts = datetime.now(UTC).isoformat()

    entities, case_id = _entities(q, store, memory)

    # ── XAI: copilot_start ──
    _copilot_emit(store, {
        "event_type": "copilot_start",
        "case_id": case_id or q.session_id or "general",
        "version": 0,
        "agent": "copilot",
        "detail": q.text[:300],
        "ts": ts,
    })

    turn = Turn(query=q, entities=entities, kg=kg, store=store, case_id=case_id)
    ctx = RequestContext(has_docs=bool(q.docs), case_id=case_id,
                         case_audited=bool(case_id) and turn.record() is not None,
                         memory=memory.summary() if memory else "")
    nlu = understand(q.text, entities, ctx)
    spec = REGISTRY[nlu.intent]
    meta = {"nlu": nlu.as_dict(), "entities": entities.as_dict(), "case_id": case_id}

    # ── XAI: copilot_nlu ──
    _copilot_emit(store, {
        "event_type": "copilot_nlu",
        "case_id": case_id or q.session_id or "general",
        "version": 0,
        "agent": "copilot_nlu",
        "detail": f"Intent: {nlu.intent} (method: {nlu.method})",
        "intent": nlu.intent,
        "nlu_method": nlu.method,
        "ts": datetime.now(UTC).isoformat(),
    })

    def respond(reply: str, data: dict | None = None, needs: str | None = None) -> CopilotResponse:
        # ── XAI: copilot_end ──
        elapsed = (time.perf_counter() - t0) * 1000
        _copilot_emit(store, {
            "event_type": "copilot_end",
            "case_id": case_id or q.session_id or "general",
            "version": 0,
            "agent": "copilot",
            "detail": reply[:300],
            "intent": spec.name,
            "duration_ms": round(elapsed, 1),
            "status": "needs_slot" if needs else "done",
            "ts": datetime.now(UTC).isoformat(),
        })
        return CopilotResponse(intent=spec.name, group=spec.group, reply=reply,
                               suggestions=[] if needs else list(spec.follow_ups),
                               data={**(data or {}), **meta, **({"needs": needs} if needs else {})})

    for need in spec.needs:
        missing = _missing(need, turn)
        if missing:
            return respond(missing, needs=need)
    try:
        out = spec.handler(turn)
    except intake.IntakeError as exc:
        return respond(f"The documents could not be read: {exc}")
    except LookupError as exc:
        return respond(str(exc))
    except (ValueError, KGError) as exc:
        return respond(f"The knowledge graph could not answer: {exc}")
    return respond(out.text, out.data)

