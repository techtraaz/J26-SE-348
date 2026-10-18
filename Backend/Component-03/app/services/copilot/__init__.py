"""Audit Copilot: natural-language requests over audits, rules and standards.

    text -> entities (code) -> intent (LLM, rules fallback) -> slot check -> handler

Intents live in handlers.py (registry in registry.py). Replies are built in
code from saved results and KG data.
"""
from app.schemas.copilot import CopilotQuery, CopilotResponse
from app.services import intake
from app.services.copilot import handlers  # noqa: F401 - registers the intents
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


def _entities(q: CopilotQuery, store: ResultStore) -> tuple[Entities, str | None]:
    """Extract entities; a case named in the text wins over the request's case_id.
    Cases the store knows are matched only when no case is named otherwise."""
    ent = extract(q.text)
    case_id = ent.case_ids[0] if ent.case_ids else q.case_id
    if case_id is None:
        known = [r["case_id"] for r in store.latest_all()]
        ent = extract(q.text, known_case_ids=known)
        case_id = ent.case_ids[0] if ent.case_ids else None
    latest = store.latest(case_id) if case_id else None
    if latest:
        docs = [d["doc_id"] for d in latest["case"]["docs"]]
        ent.doc_ids = extract(q.text, known_doc_ids=docs).doc_ids
    return ent, case_id


def answer(q: CopilotQuery, kg: KGClient | None = None,
           store: ResultStore | None = None) -> CopilotResponse:
    kg = kg or default_kg()
    store = store or default_store()
    entities, case_id = _entities(q, store)
    turn = Turn(query=q, entities=entities, kg=kg, store=store, case_id=case_id)
    ctx = RequestContext(has_docs=bool(q.docs), case_id=case_id,
                         case_audited=bool(case_id) and turn.record() is not None)
    nlu = understand(q.text, entities, ctx)
    spec = REGISTRY[nlu.intent]
    meta = {"nlu": nlu.as_dict(), "entities": entities.as_dict(), "case_id": case_id}

    def respond(reply: str, data: dict | None = None, needs: str | None = None) -> CopilotResponse:
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
