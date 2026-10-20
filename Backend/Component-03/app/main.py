"""FastAPI doors for Component-03."""
import json
from typing import Annotated, Any

from fastapi import Body, FastAPI, HTTPException, Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import config
from app.schemas.chat import ExternalMessage
from app.schemas.copilot import SESSION_ID_PATTERN, CopilotQuery
from app.services import c1_review, chat, copilot, intake, orchestrator, rules
from app.services.chat_store import default_chat_store
from app.services.kg_client import KGError, default_kg
from app.services.store import StoreError, case_summary, default_store

app = FastAPI(title="NOMOS Component 03 — Audit Reasoning")
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

CASE_BODY = Body(..., examples=[{"case_id": "CASE-1", "docs": [{
    "doc_id": "BS-2026", "doc_type": "balance_sheet", "period_year": 2026,
    "fields": {"assets": 50000, "liabilities": 30000, "capital": 20000},
    "confidences": {"assets": 0.97}, "methods": {"assets": "paddleocr"}}]}])
DOCS_BODY = Body(..., examples=[{"docs": [], "materiality": 50000}])
SessionId = Annotated[str, Path(pattern=SESSION_ID_PATTERN)]
CaseId = Annotated[str, Path(pattern=SESSION_ID_PATTERN)]


class C1PreviewRequest(BaseModel):
    case_id: str = Field(pattern=SESSION_ID_PATTERN)
    documents: list[c1_review.C1Input] = Field(min_length=1, max_length=50)


class C1ConfirmRequest(BaseModel):
    case_id: str = Field(pattern=SESSION_ID_PATTERN)
    documents: list[c1_review.ReviewedDocument] = Field(min_length=1, max_length=50)


def _case(payload: Any):
    try:
        return intake.normalize_case(payload)
    except intake.IntakeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _store_call(fn, *args):
    try:
        return fn(*args)
    except StoreError as exc:
        raise HTTPException(status_code=503, detail=f"Result store unavailable: {exc}") from exc


@app.get("/health")
def health():
    return {"ok": True, "model": config.MODEL_NAME, "llm_enabled": config.LLM_ENABLED,
            "allow_free_cypher": config.ALLOW_FREE_CYPHER, "kg_mode": config.KG_MODE,
            "kg_url": config.KG_URL or None, "store": config.STORE_MODE,
            "intake_version": intake.INTAKE_VERSION}


@app.post("/audit/intake")
def audit_intake(payload: dict = CASE_BODY):
    """Normalize and check a case without running the audit."""
    case = _case(payload)
    return {"contract_version": intake.INTAKE_VERSION, "case": case.model_dump(),
            "issues": [f.message for f in rules.data_quality_findings(case)]}


@app.post("/audit/intake/c1/preview")
def audit_intake_c1_preview(body: C1PreviewRequest):
    """What C3 reads from Component-01 documents, for the Library review. Saves nothing."""
    try:
        return {"case_id": body.case_id,
                "documents": c1_review.preview(body.case_id, body.documents, default_kg())}
    except KGError as exc:
        raise HTTPException(status_code=502, detail=f"Knowledge graph error: {exc}") from exc


@app.post("/audit/intake/c1/confirm")
def audit_intake_c1_confirm(body: C1ConfirmRequest):
    """The reviewer's decisions become case documents (values and confidences set by C3).
    Audit them with POST /audit/run or /audit/{case_id}/evidence."""
    try:
        return {"contract_version": intake.INTAKE_VERSION,
                **c1_review.confirm_case(body.case_id, body.documents, default_kg())}
    except intake.IntakeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except KGError as exc:
        raise HTTPException(status_code=502, detail=f"Knowledge graph error: {exc}") from exc


def _check_session(session_id: str | None) -> None:
    if session_id is not None and not intake.SAFE_ID_RE.fullmatch(session_id):
        raise HTTPException(status_code=422, detail=f"invalid session_id {session_id!r}")


@app.post("/audit/run")
def audit_run(payload: dict = CASE_BODY, session_id: str | None = None):
    """Run the full audit; the result is saved as the next version of the case.
    With ?session_id= the result also appears in that chat."""
    _check_session(session_id)
    result = _store_call(orchestrator.run_case, _case(payload))
    if session_id:
        _store_call(chat.record_audit, default_chat_store(), session_id, result)
    return result.model_dump()


@app.post("/audit/run/stream")
def audit_run_stream(payload: dict = CASE_BODY):
    """One NDJSON line per finished agent, then the saved result."""
    case = _case(payload)
    store = _store_call(default_store)
    _store_call(store.latest, case.case_id)  # fail before streaming if the store is down

    def lines():
        try:
            for chunk in orchestrator.stream_case(case, store=store):
                yield json.dumps(chunk, default=str) + "\n"
        except StoreError as exc:
            yield json.dumps({"event": "error", "detail": f"Result store unavailable: {exc}"}) + "\n"
    return StreamingResponse(lines(), media_type="application/x-ndjson")


@app.post("/audit/{case_id}/evidence")
def audit_append(case_id: str, payload: dict = DOCS_BODY, session_id: str | None = None):
    """Add documents to the latest version of a case and re-run (new version)."""
    _check_session(session_id)
    try:
        result = _store_call(lambda: orchestrator.append_evidence(
            case_id, payload.get("docs", []), materiality=payload.get("materiality")))
        if session_id:
            _store_call(chat.record_audit, default_chat_store(), session_id, result)
        return result.model_dump()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except intake.IntakeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/audit/cases")
def audit_cases(limit: int = 100):
    """Audited cases, newest first: latest version, status and finding counts."""
    records = _store_call(default_store().latest_all, max(1, min(limit, 500)))
    return {"cases": [case_summary(r) for r in records]}


@app.get("/audit/{case_id}/versions")
def audit_versions(case_id: str):
    return {"case_id": case_id, "versions": _store_call(default_store().versions, case_id)}


@app.get("/audit/{case_id}/latest")
def audit_latest(case_id: str):
    rec = _store_call(default_store().latest, case_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"No saved audit for case {case_id!r}")
    return rec


@app.get("/audit/{case_id}/versions/{version}")
def audit_version(case_id: str, version: int):
    rec = _store_call(default_store().get, case_id, version)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id!r} has no version {version}")
    return rec


@app.post("/copilot/query")
def copilot_query(q: CopilotQuery):
    """Without session_id each request stands alone; with it the turn is saved
    and follow-ups use the session's memory."""
    if q.session_id:
        return _store_call(chat.converse, q, default_kg(), default_store(),
                           default_chat_store()).model_dump()
    return _store_call(copilot.answer, q).model_dump()


@app.get("/chat/sessions")
def chat_sessions(limit: int = 100, case_id: str | None = None):
    """Chats, most recently active first."""
    rows = _store_call(default_chat_store().list_sessions, max(1, min(limit, 500)), case_id)
    return {"sessions": [s.model_dump() for s in rows]}


@app.get("/chat/{session_id}/messages")
def chat_messages(session_id: SessionId, before: int | None = None, limit: int = 50):
    """History oldest first, with findings filled in. Page back with ?before=<seq>."""
    rows = _store_call(chat.history, default_chat_store(), default_store(), session_id,
                       before, max(1, min(limit, 200)))
    return {"session_id": session_id, "messages": [m.model_dump() for m in rows]}


@app.delete("/chat/{session_id}")
def chat_delete(session_id: SessionId):
    """Delete a chat and its messages. Audit results are not touched."""
    if not _store_call(default_chat_store().delete_session, session_id):
        raise HTTPException(status_code=404, detail=f"No chat {session_id!r}")
    return {"deleted": session_id}


@app.post("/chat/case/{case_id}/messages")
def chat_post_to_case(case_id: CaseId, msg: ExternalMessage):
    """For other components, e.g. C4 when a report is ready: the message goes to
    every chat of the case. Only the case_id (and version) from C3's events is needed."""
    rows = _store_call(chat.post_to_case, default_chat_store(), case_id, msg)
    return {"case_id": case_id, "messages": [m.model_dump() for m in rows]}


@app.get("/kg/rules/{doc_type}")
def kg_rules(doc_type: str):
    kg = default_kg()
    try:
        out = {"doc_type": doc_type,
               "rules": [r.model_dump() for r in kg.get_rules(doc_type)],
               "check_rules": [r.model_dump() for r in kg.get_check_rules(doc_type)]}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KGError as exc:
        raise HTTPException(status_code=502, detail=f"Knowledge graph error: {exc}") from exc
    return {**out, "kg_source": kg.source}
