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
| GET | `/audit/cases` | audited cases, newest first (latest version, status, counts) |
| GET | `/audit/{case_id}/versions` | every saved version (summary) |
| GET | `/audit/{case_id}/versions/{v}` | one saved version, with its input case |
| GET | `/audit/{case_id}/latest` | newest saved version |
| POST | `/copilot/query` | `{text, case_id?, docs?}` → natural-language request (see Copilot) |
| GET | `/kg/rules/{doc_type}` | the KG rules C3 would apply |
| GET | `/chat/sessions[?case_id=]` | saved chats, most recently active first |
| GET | `/chat/{session_id}/messages[?before=<seq>&limit=]` | history, oldest first, findings filled in |
| DELETE | `/chat/{session_id}` | delete a chat (audit results are kept) |
| POST | `/chat/case/{case_id}/messages` | another component posts into a case's chat (C4 report ready) |

`POST /audit/run`, `POST /audit/{case_id}/evidence` and `POST /copilot/query`
accept a `session_id`; the turn or result is then saved in that chat.

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

## Copilot

`app/services/copilot/`:

```
text -> entities (code) -> intent (rules if confident, else LLM among the top 3) -> slot check -> handler
```

| Group (SO5) | Intents |
|---|---|
| rule_query | `rule_lookup` (rules/limits per doc type, compares a stated amount), `rule_explain`, `standard_search` |
| case_query | `case_status`, `list_findings` (filter by severity/rule/doc/type/category/review), `explain_finding`, `evidence_gaps`, `compare_versions`, `list_versions`, `search_cases` |
| evidence_append | `evidence_append` |
| fresh_audit | `fresh_audit`, `rerun_audit`, `whatif_check` (audits a described transaction; not saved, not sent to C4) |
| other | `help` |

- **Adding an intent:** write one `@intent(...)` handler in `handlers.py`, with a
  description, examples, patterns, signals and needs. The LLM prompt, the rules
  fallback, the slot checks and the help text all come from it.
- **Entities** (IDs, rule ids, severities, amounts…) are extracted in code only;
  a small model was measured inventing them.
- **Replies** are built in code from saved results and KG data.
- **The response** has `intent`, `group`, `reply`, `suggestions` (follow-up
  questions) and `data`. `data.findings` holds any findings the reply is about;
  `data.nlu` says how the intent was chosen and what the rules and the LLM said.
- **Context counts:** documents attached to an already-audited case are added
  to it (evidence append) unless the text explicitly asks for a fresh audit.
- **Any model:** set `C03_LLM_PROVIDER`, `C03_LLM_MODEL` and `C03_LLM_BASE_URL`.
  New providers go in `app/services/llm/providers.py`.

SO5 evaluation (`eval/copilot_intents.jsonl`, 63 labelled queries):

```powershell
.venv\Scripts\python.exe -m scripts.eval_copilot --out eval/results_copilot.json
```

| Mode | Intent acc. | Group acc. | Mean latency |
|---|---|---|---|
| rules | 98.4% | 100% | ~0 s |
| llm (phi4-mini, all 15 intents) | 87.3% | 96.8% | 2.8 s |
| auto (rules + phi4-mini on 22/63) | 96.8% | 100% | 1.0 s |

The rules were written alongside this set, so their score is optimistic. An
independent set written by other people is needed for the dissertation figure.

## Chat sessions and memory

`app/services/chat.py`, `chat_store.py`, `copilot/memory.py`. MongoDB:
`c03_chat_sessions` (one per chat, with its memory), `c03_chat_messages`
(ordered by a per-session `seq`), `c03_chat_counters`.

- A case's own chat has `session_id == case_id` (one chat per case for now);
  general chats use other ids (`GEN-...`). `session_id` is separate from
  `case_id`, so several chats per case need no redesign.
- Messages store findings **by reference** (`refs: {version, finding_ids}`) and
  are filled in from the saved audit version when read. Saved versions never
  change, so a message always shows what was said then. What-if findings are
  in no saved audit, so they are stored inline.
- **Memory** is a small structured context per session, updated in code after
  each turn: `case_id`, `version`, `last_intent`, `finding_ids`, `filters`.
  "why did that one fire?" uses the findings shown last, "only the high ones"
  narrows the last list, and with no case named the last case is used. The LLM
  only gets a one-line summary of it; the transcript is never fed to the model.
- **Reports from C4:** `POST /chat/case/{case_id}/messages` with
  `{"role": "report", "text": "...", "version": 3, "data": {"report_url": "..."}, "source": "c4"}`.
  C4 needs only the `case_id` and `version` from C3's events; C3 routes the
  message to every chat of that case (creating the case's chat if needed).

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
