# Component 03 — Multi-Agent Audit Reasoning + Audit Copilot

Clean base. Real work lives here (test folder elsewhere is only playground).

## Run

```powershell
uv sync
uv run uvicorn app.main:app --reload --port 8003
```

## Doors (FastAPI)

- `GET /health` — alive check
- `POST /audit/run` — run full case, returns findings
- `POST /copilot/query` — chat slot (keyword router now, LLM later)
- `GET /kg/rules/{doc_type}` — shows what we ask from KG

## Rules

- Maths checks run in plain Python, not LLM (small model is bad at maths).
- LLM only explains, never decides pass/fail and never writes Cypher.
- `ALLOW_FREE_CYPHER = False` is locked in `app/config.py`.
