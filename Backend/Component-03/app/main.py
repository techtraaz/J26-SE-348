"""FastAPI doors for Component-03."""
import json
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app import config
from app.schemas.copilot import CopilotQuery
from app.services import copilot, intake, orchestrator, rules
from app.services.kg_client import KGError, default_kg
from app.services.store import StoreError, default_store

app = FastAPI(title="NOMOS Component 03 — Audit Reasoning")
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

CASE_BODY = Body(..., examples=[{"case_id": "CASE-1", "docs": [{
    "doc_id": "BS-2026", "doc_type": "balance_sheet", "period_year": 2026,
    "fields": {"assets": 50000, "liabilities": 30000, "capital": 20000},
    "confidences": {"assets": 0.97}, "methods": {"assets": "paddleocr"}}]}])
C1_BODY = Body(..., examples=[{"case_id": "CASE-1", "documents": [{
        "doc_type": "invoice", "period_year": 2026, "extraction": {
            "document_id": "INV-001", "run": {"status": "succeeded"},
            "regions": [{"sequence": 1, "page_number": 1, "text": "Rs. 125,000.00",
                         "confidence": 0.93, "provenance": "paddleocr", "field_key": "amount"}]}}]}])
DOCS_BODY = Body(..., examples=[{"docs": []}])


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


@app.post("/audit/intake/c1")
def audit_intake_c1(payload: dict = C1_BODY,
                    run: bool = False):
    """Map Component-01 extractions to a case; with ?run=true also audit it."""
    try:
        case, unmapped = intake.from_c1(payload.get("case_id", ""), payload.get("documents", []))
    except intake.IntakeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    out = {"contract_version": intake.INTAKE_VERSION, "case": case.model_dump(),
           "unmapped_regions": unmapped,
           "issues": [f.message for f in rules.data_quality_findings(case)]}
    if run:
        out["result"] = _store_call(orchestrator.run_case, case).model_dump()
    return out


@app.post("/audit/run")
def audit_run(payload: dict = CASE_BODY):
    """Run the full audit; the result is saved as the next version of the case."""
    return _store_call(orchestrator.run_case, _case(payload)).model_dump()


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
def audit_append(case_id: str, payload: dict = DOCS_BODY):
    """Add documents to the latest version of a case and re-run (new version)."""
    try:
        return _store_call(orchestrator.append_evidence, case_id,
                           payload.get("docs", [])).model_dump()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except intake.IntakeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
    return _store_call(copilot.answer, q).model_dump()


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
