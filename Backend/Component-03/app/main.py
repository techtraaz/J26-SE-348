"""FastAPI doors — waiter outside, agents are kitchen inside."""
from fastapi import FastAPI
from app import config
from app.schemas.case import AuditCase
from app.schemas.copilot import CopilotQuery
from app.services import orchestrator, copilot
from app.services.kg_client import KGClient

app = FastAPI(title="NOMOS Component 03 — Audit Reasoning")


@app.get("/health")
def health():
    return {"ok": True, "model": config.MODEL_NAME,
            "allow_free_cypher": config.ALLOW_FREE_CYPHER}


@app.post("/audit/run")
def audit_run(case: AuditCase):
    return orchestrator.run_case(case, KGClient()).model_dump()


@app.post("/copilot/query")
def copilot_query(q: CopilotQuery):
    return copilot.answer(q).model_dump()


@app.get("/kg/rules/{doc_type}")
def kg_rules(doc_type: str):
    return {"doc_type": doc_type, "rules": KGClient().get_rules(doc_type),
            "check_rules": KGClient().get_check_rules(doc_type)}
