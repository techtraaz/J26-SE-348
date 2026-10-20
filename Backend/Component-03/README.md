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
| POST | `/audit/intake/c1/preview` | what C3 reads from C1 documents, for the Library review (saves nothing) |
| POST | `/audit/intake/c1/confirm` | the reviewer's decisions -> case documents (then audit them) |
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

**Component-01.** C1 reads documents line by line (text, raw confidence, box)
with no field template. C3 turns lines into fields and a person reviews them in
the Library before auditing (`app/services/field_mapper.py`, `c1_review.py`):

1. **Source:** C1's human-verified record when it has one
   (`GET /api/v1/documents/{id}/verified`, proposed in
   [docs/c1_verified_record_contract.md](docs/c1_verified_record_contract.md)),
   else its machine extraction (`/extraction`).
2. **Rules:** label and amount on one line, the amount to the right on the same
   row (by box), or on the next line. Labels are matched against C2's field
   names and aliases (`GET /query/fields`) plus everyday receipt wording. The
   first amount on a line is the current period. Dates, times, ids and column
   heading years are never read as amounts. Document type and year are only
   suggested.
3. **LLM fallback:** only for **required** fields still missing (CHK-006's list
   and the policy-limit field) when lines holding numbers are unused. The LLM
   returns line ids from a fixed list; the value is read from that line in code,
   so it cannot invent a number. An optional rule input that is absent (e.g. no
   "cash out" on an invoice) is reported as "this check will not run", never guessed.
4. **Review:** confirm type, year and parent; edit values; confirm AI matches;
   add a field from an unused line; then **confirm**. C3 recomputes every value
   from its line and sets every confidence itself:

| How the value was read | Confidence | `methods` ends with |
|---|---|---|
| verified C1 record | 1.0 (a person confirmed it) | `c3:rules` / `c3:confirmed` |
| machine extraction | lowest raw score of its lines | `c3:rules` / `c3:confirmed` |
| AI match, not confirmed | capped at 0.4, so REV-001 "not confirmed" | `c3:unconfirmed` |
| typed by the reviewer | 1.0 | `c3:human` |

Each document keeps `source: {component, document_id, run_id, verified_version,
confirmed_by}`; a machine extraction (`verified_version: null`) raises REV-008,
and every finding's reasoning chain names its source.

Mapping quality: `.venv\Scripts\python.exe -m scripts.eval_fields` (labelled
documents in `eval/field_mapping/`). Current set (4 documents written for this):
rules 100% precision / 90% recall, rules + phi4-mini 100% / 100%, type and year
100%. Add real C1 documents to make it meaningful.

**Component-02.** `KG_URL` is C2's base URL (e.g. `http://localhost:8002`). C3
calls only C2's fixed `GET /query/...` endpoints, never `/query/cypher`:

| Endpoint | Used by |
|---|---|
| `rules`, `check-rules` | Compliance, Anomaly (which rules apply to each document type) |
| `fields` | Library field mapping (line items and aliases) |
| `rules/{id}/explain` | Reasoning: basis, cited paragraphs (`policy_ids`), assertions, risks |
| `standards/{code}` | Reasoning: a cited standard that is not current (e.g. superseded) gets a caution in the chain |
| `evidence-chain/{doc_id}` | Reasoning: linked documents (only the document itself until C2's ledger exists) |
| `sections`, `definitions`, `line-items`, `search` | Copilot: "LKAS 2:9", "define net realisable value", "what does capital mean", topics |

`KG_MODE=auto` uses the bundled mock (same shapes and rules as C2's seed) only
when C2 is unreachable, and the result says `kg_source: "mock_fallback"`.
Reasoning's KG lookups run in parallel, so the live KG's network round trips
do not add up per rule.

**Before relying on a live C2**, check it against what C3 needs:

```powershell
.venv\Scripts\python.exe -m scripts.check_kg_contract          # uses KG_URL
```

It lists the rules per document type, which agent runs each and whether C3
can evaluate it, the explanations and cited standards' status, and flags any
reply C3 could not use (exit code 1) or an unreachable C2 (exit code 2).

## Materiality

A case may carry `materiality` (an amount, SLAuS 320), set by the auditor in the
Library or sent with the case JSON (`{"case_id": ..., "materiality": 50000, "docs": [...]}`).
Evidence appends and re-runs keep it unless a new value is sent.

- A failed rule whose **amount difference** is below it stays a finding, at
  `low` severity, and its message says so ("the difference 5.00 is below the case
  materiality 50,000.00; C2 rates this rule high"). Nothing is dropped.
- Only plain amount comparisons have a difference (`assets == liabilities +
  capital`, `inventories <= inventory_nrv`). Fraud patterns (CHK-005: material
  whatever the amount, SLAuS 240), ratios and thresholds (CHK-004) and policy
  limits (POL-07) are never softened.
- No materiality = every difference above 1 cent counts at the rule's severity.

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
| REV-008 | document read from C1's machine extraction, not human-verified |

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
