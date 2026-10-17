"""FastAPI doors — waiter outside, agents are kitchen inside."""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.schemas.copilot import CopilotQuery
from app.services import copilot, intake, orchestrator
from app.services.kg_client import default_kg

app = FastAPI(title="NOMOS Component 03 — Audit Reasoning")

# Allow browser frontend (vite on :5173) to call this backend (:8003).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True, "model": config.MODEL_NAME,
            "allow_free_cypher": config.ALLOW_FREE_CYPHER,
            "kg_mode": config.KG_MODE}


@app.post("/audit/intake")
def audit_intake(payload: dict):
    """Canonicalize + validate a case before it reaches the agents."""
    try:
        case = intake.normalize_case(payload)
    except intake.IntakeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"contract_version": intake.INTAKE_VERSION,
            "case": case.model_dump(), "issues": intake.validate_case(case)}


@app.post("/audit/intake/extraction")
def audit_intake_extraction(payload: dict):
    """Bridge C1 extraction output onto canonical case documents."""
    try:
        case = intake.from_extraction(
            payload.get("extraction", {}), payload.get("case_id", ""),
            payload.get("page_documents", []))
    except intake.IntakeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"contract_version": intake.INTAKE_VERSION,
            "case": case.model_dump(), "issues": intake.validate_case(case)}


@app.post("/audit/run")
def audit_run(payload: dict):
    """Canonicalize at the door, then run the full audit."""
    try:
        case = intake.normalize_case(payload)
    except intake.IntakeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return orchestrator.run_case(case, default_kg()).model_dump()


@app.post("/audit/run/stream")
def audit_run_stream(payload: dict):
    """Real per-agent pills: streams one update per finished node."""
    import json

    from fastapi.responses import StreamingResponse

    try:
        case = intake.normalize_case(payload)
    except intake.IntakeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    def gen():
        for chunk in orchestrator.stream_case(case, default_kg()):
            yield json.dumps(chunk, default=str) + "\n"
    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/copilot/query")
def copilot_query(q: CopilotQuery):
    return copilot.answer(q).model_dump()


@app.get("/kg/rules/{doc_type}")
def kg_rules(doc_type: str):
    kg = default_kg()
    try:
        rules = kg.get_rules(doc_type)
        check_rules = kg.get_check_rules(doc_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"doc_type": doc_type, "rules": rules, "check_rules": check_rules}
