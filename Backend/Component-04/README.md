# Component 04 — Explainability and Final Audit Report

Component 04 explains what Component 03's agents did and turns a saved audit
into the final PDF report. It is a **sidecar**: Component 03 never waits on it,
and keeps working if Component 04 is offline.

## What it does

- **Live Thinking timeline.** Reads Component 03's XAI trace events from MongoDB
  (`nomos_xai.c03_callback_traces`), turns each step into a readable row and
  streams it to the Explainability panel over SSE (`GET /xai/stream/{stream_id}`,
  where the stream is a case id or a chat session id).
- **Review Agent.** After every audit and Copilot turn, rules decide a verdict and
  next steps from the trace; the LLM writes a short summary (checked against the
  facts, with a fixed-wording fallback). Saved in `c04_reviews`.
- **Final audit report.** `POST /report/generate` builds a PDF from one saved audit
  record (`c03_audit_results`), uploads it to the S3-compatible object storage and
  returns its download link (contract: `Component-03/docs/c4_report_contract.md`).

## Run

```powershell
cp .env.example .env     # then fill in MongoDB, LLM and object storage settings
uv sync
uv run uvicorn app.main:app --reload --port 8004
```

Tests use an in-memory MongoDB and S3 bucket and never touch real services:

```powershell
uv run pytest -q
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | alive check |
| GET | `/xai/stream/{stream_id}` | SSE: live steps, stages, runs and reviews (older history replayed on connect) |
| DELETE | `/xai/history/{stream_id}` | after a chat is deleted: remove its Copilot-turn reviews and history |
| POST | `/report/generate` | `{"audit_id": "<case>:v<n>"}` (or `case_id` + `version`) → `{"status": "report_ready", "download_url": ...}` |
| POST | `/report/generate/{case_id}` | report of the case's latest audit |
| GET | `/report/download/{file}.pdf` | the PDF (inline; `?download=1` to save) |
| GET | `/report/list/{case_id}` | a case's reports (no files) |
| GET | `/runs`, `/traces/{case_id}` | local SQLite view of processed runs and steps |

## Data

| Where | What | Kept |
|---|---|---|
| `c03_callback_traces` (C03 writes, C04 reads) | trace events | permanently; a chat's Copilot-turn traces are deleted with the chat |
| `c04_reviews` | one Review Agent result per run | with its run; chat reviews deleted with the chat |
| `c04_reader_state` | how far the trace reader has read | — |
| `c04_reports` | report index (case, version, verdict, score, object key) | permanently |
| object storage `c04-reports/<case>/<report>.pdf` | the report PDFs | permanently |
| `trace_store.db` (local SQLite) | processed runs and steps | local working copy |

On restart the reader continues from its saved position; it never re-reads every
trace. Older events are replayed on demand (render only, no writes, no LLM calls)
the first time the panel opens a stream.

## Switching the LLM

Only `.env` changes. For an OpenAI-compatible server (e.g. Qwen on vLLM):

```
C04_LLM_PROVIDER=openai
C04_LLM_API_URL=https://<pod-host>/v1
C04_LLM_MODEL=<model name the server lists at /v1/models>
C04_LLM_API_KEY=<key, if the server needs one>
```
