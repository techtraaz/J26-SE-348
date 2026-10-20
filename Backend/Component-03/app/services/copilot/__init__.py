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
# One RunTracer per turn: events are queued for the background writer, so a
# slow or offline MongoDB never delays the reply.

import time
from datetime import UTC, datetime

from app.services import xai_trace


def answer(q: CopilotQuery, kg: KGClient | None = None, store: ResultStore | None = None,
           memory: SessionContext | None = None) -> CopilotResponse:
    """One request. `memory` (a chat session's context) lets follow-ups such as
    "why did that one fire?" resolve; without it every request stands alone."""
    kg = kg or default_kg()
    store = store or default_store()
    t0 = time.perf_counter()
    ts = datetime.now(UTC).isoformat()

    entities, case_id = _entities(q, store, memory)
    # Keyed by the chat session the user is looking at (a case chat's session is
    # its case id), so a general chat that names a case still sees its own steps.
    tracer = xai_trace.RunTracer(q.session_id or case_id or "general", 0,
                                 store.trace_exporter(), kind="copilot")

    # ── XAI: copilot_start ──
    tracer.emit({
        "event_type": "copilot_start",
        "agent": "copilot",
        "detail": q.text[:300],
        "ts": ts,
    })

    xai_trace.record(tracer, "copilot_nlu", "entities", "ok", case_id=case_id,
                     found=entities.as_dict(), from_memory=bool(memory and memory.case_id == case_id))
    turn = Turn(query=q, entities=entities, store=store, case_id=case_id,
                kg=xai_trace.traced_kg(kg, tracer, "copilot"))
    ctx = RequestContext(has_docs=bool(q.docs), case_id=case_id,
                         case_audited=bool(case_id) and turn.record() is not None,
                         memory=memory.summary() if memory else "")
    with xai_trace.scope(tracer, "copilot_nlu"):
        nlu = understand(q.text, entities, ctx)
    spec = REGISTRY[nlu.intent]
    meta = {"nlu": nlu.as_dict(), "entities": entities.as_dict(), "case_id": case_id,
            "trace_id": tracer.trace_id}  # this turn's XAI trace (Component-04's "Explain")

    # ── XAI: copilot_nlu ──
    tracer.emit({
        "event_type": "copilot_nlu",
        "agent": "copilot_nlu",
        "detail": f"Intent: {nlu.intent} (method: {nlu.method})",
        "intent": nlu.intent,
        "nlu_method": nlu.method,
        "ts": datetime.now(UTC).isoformat(),
    })

    def respond(reply: str, data: dict | None = None, needs: str | None = None) -> CopilotResponse:
        # ── XAI: copilot_end ──
        elapsed = (time.perf_counter() - t0) * 1000
        tracer.emit({
            "event_type": "copilot_end",
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
            xai_trace.record(tracer, "copilot", "decision", "skipped",
                             decision=f"{spec.name} needs more information", reason=missing)
            return respond(missing, needs=need)
    try:
        with xai_trace.scope(tracer, "copilot"):
            out = spec.handler(turn)
    except intake.IntakeError as exc:
        return respond(f"The documents could not be read: {exc}")
    except LookupError as exc:
        return respond(str(exc))
    except (ValueError, KGError) as exc:
        return respond(f"The knowledge graph could not answer: {exc}")
    return respond(out.text, out.data)

