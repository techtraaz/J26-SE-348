# Component 03 — Multi-Agent Audit Reasoning + Audit Copilot

Takes a case (documents with extracted fields), runs five agents over the
Component-02 knowledge graph, and saves a versioned audit result.

```
data_quality -> (compliance || anomaly) -> reasoning -> evidence_validation
```

## Run

`uv` is not installed on this machine; use the venv Python.

```powershell
copy .env.example .env     # fill in C03_MONGODB_URI, KG_URL
.venv\Scripts\python.exe -m pip install pymongo mongomock   # if missing
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8003
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
```

Without a MongoDB URI (or with `C03_STORE_MODE=memory`) results live in memory
only. With a URI, an unreachable MongoDB makes audit calls answer **503**: a
result is never returned unless it was saved.

## Doors

| Method | Path | What |
|---|---|---|
| GET | `/health` | settings in use (KG mode, store, LLM) |
| POST | `/audit/intake` | normalize + check a case, no run |
| POST | `/audit/intake/c1[?run=true]` | map Component-01 extractions to a case (and run it) |
| POST | `/audit/run` | run and save the next version |
| POST | `/audit/run/stream` | NDJSON: one line per finished agent, then the result |
| POST | `/audit/{case_id}/evidence` | add docs to the latest version and re-run |
| GET | `/audit/{case_id}/versions` | every saved version (summary) |
| GET | `/audit/{case_id}/versions/{v}` | one saved version, with its input case |
| GET | `/audit/{case_id}/latest` | newest saved version |
| POST | `/copilot/query` | `{text, case_id?, docs?}` → rule query / evidence append / fresh audit |
| GET | `/kg/rules/{doc_type}` | the KG rules C3 would apply |

## Inputs

**Component-01.** `POST /audit/intake/c1` takes C1's `GET /documents/{id}/extraction`
reply plus what C1 does not know (`doc_type`, `period_year`, `parent_doc_id`). A
region with a `field_key` becomes that field (value = text, confidence = raw
score, method = provenance). Regions without a `field_key` are counted in
`unmapped_regions`. Two regions with different text for one field are both kept
and flagged (REV-003).

**Component-02.** `KG_URL` is C2's base URL (e.g. `http://localhost:8002`). C3
calls only C2's fixed `GET /query/...` endpoints: `rules`, `check-rules`,
`evidence-chain`, `rules/{id}/explain`, `search`. Never `/query/cypher`.
`KG_MODE=auto` uses the bundled mock (same shapes and rules as C2's seed) only
when C2 is unreachable, and the result says `kg_source: "mock_fallback"`.

## How rules run

C2 check rules are data. Their expressions (e.g.
`abs(assets - prior.assets) / abs(prior.assets) <= 0.30`) are evaluated by a
safe evaluator, and names are matched to document fields through the rule's
`variables` (line item + aliases). Rules that compare documents
(`child.`/`parent.`/`prior.`) or are fraud patterns run in Anomaly; the rest run
in Compliance. CHK-006 (required fields) is checked in code by Data Quality.

Rule ids: `CHK-*`/`POL-*` come from the KG. `REV-*` are C3 review items, never
violations:

| Id | Meaning |
|---|---|
| REV-001 | low-confidence field |
| REV-002 | unsupported document type |
| REV-003 | value unreadable as a number, or conflicting values |
| REV-004 | intake issue (missing parent, confidence outside 0..1, no fields) |
| REV-005 | KG links a document that is not in the case |
| REV-006 | KG rule could not be evaluated |
| REV-007 | KG rules could not be loaded (those checks did not run) |

`evidence_validation`: `passed` (every claimed value matched), `existence_only`
(cited docs exist, no values to check), `failed` (kept, flagged, and logged in
`rejected_findings`), `unverified` (no evidence cited).

## Outputs for Component-04

- MongoDB `nomos_xai.c03_audit_results`: one record per run, `_id`
  `"<case_id>:v<version>"`, every `AuditResult` field plus `case` (the input).
  Saved **before** `pipeline_end` is published.
- Redis `nomos:trace_events`: `pipeline_start`, `agent_end` ×5, `pipeline_end`.
  These are C4's shapes, plus `version` (start/end), `status` (end) and
  `traces` (all trace lines of an agent).

## Locked rules

Maths and pass/fail run in Python. The LLM (self-hosted, Ollama) only writes
short trace lines, every number it writes must appear in its prompt, and it
never writes Cypher. `ALLOW_FREE_CYPHER = False`.
