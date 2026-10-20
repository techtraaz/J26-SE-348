# Component 01 — Data Extraction

Turns uploaded documents into **human-verified records** for the audit components.

```text
upload (PDF/image) → page images → OCR (PaddleOCR) → review in the Library → confirm → verified record → Component 03
```

- Documents live in a folder library. Extraction runs in the background (one document at a time).
- A reviewer checks every line in the Library: edits text, fixes or draws boxes, deletes false lines, accepts the rest.
- **Confirming** freezes the review as an immutable, numbered **verified version**. That is what downstream components read; machine output is never edited and every human action is logged.

The UI is the **Library** tab of the shared frontend (`Frontend/`, `src/features/extraction`).

## Requirements

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- PostgreSQL (16 is tested), with a database for C1
- For the UI: Node.js and the shared frontend in `Frontend/`

## Set up

```powershell
cd Backend/Component-01
uv sync                                   # installs dependencies, incl. PaddleOCR (large)
copy .env.example .env                    # then set NOMOS_DATABASE_URL (and NOMOS_ENGINE)
createdb nomos                            # or create the database in pgAdmin
uv run alembic upgrade head               # creates or updates the tables
```

Run `uv run alembic upgrade head` again whenever you pull new migrations (`alembic/versions/`).

## Run

```powershell
uv run fastapi dev app/main.py            # API on http://127.0.0.1:8000, docs at /docs
```

Then the UI, from `Frontend/` (set `VITE_C1_BASE=http://127.0.0.1:8000` in `Frontend/.env`):

```powershell
npm install
npm run dev                               # http://localhost:5173 → Library tab
```

Check it is up: `GET http://127.0.0.1:8000/api/v1/health` returns the engine in use, the file store (`local` or `s3`) and whether the worker runs.

### Which OCR engine

| `NOMOS_ENGINE` | Use it for | Notes |
|---|---|---|
| `replay` | development, demos of the flow, frontend work | Instant. Returns one saved PaddleOCR result (`tests/fixtures/sample_invoice.default.json`) for **every** upload, so boxes line up only on that sample (`data/samples/sample_invoice.png`, not in git: ask for it). The Library says so on each document. |
| `paddle` | real extraction | About a minute per page on a laptop CPU. The first run downloads PaddleOCR's models. |

### Where files are kept

| `NOMOS_STORAGE_BACKEND` | Files (uploads and page images) live in |
|---|---|
| `local` (default) | `data/store/` on this machine (`NOMOS_STORAGE_ROOT`) |
| `s3` | an S3-compatible object store such as **Garage**: set `GARAGE_ENDPOINT`, `GARAGE_ACCESS_KEY`, `GARAGE_SECRET_KEY`, `GARAGE_BUCKET` (and `GARAGE_REGION`, default `garage`) |

The API checks the bucket at startup and refuses to start if it is unreachable or the keys are wrong. Keys in the bucket are the same paths as on disk (`documents/<id>/original.pdf`, `documents/<id>/pages/1.original.png`).

**Switching an existing installation from `local` to `s3`:** copy the files first, or older documents lose their page images:

```powershell
uv run python scripts/copy_store_to_s3.py --dry-run     # what would be copied
uv run python scripts/copy_store_to_s3.py               # copy (safe to run again)
```

Then set `NOMOS_STORAGE_BACKEND=s3` and restart. Tests never use the real store: they run on local disk, and the S3 code is tested against an in-memory S3 (moto).

All settings are listed in [.env.example](.env.example).

## API (`/api/v1`)

| Method & path | What it does |
|---|---|
| `GET /health` | Engine in use, worker running |
| `POST /folders` · `GET /folders?parent_id=` · `GET/PATCH/DELETE /folders/{id}` | Folder tree (delete: empty folders only) |
| `POST /documents` (multipart `file`, optional `folder_id`) | Upload → `202`; extraction runs in the background |
| `GET /documents?folder_id&root_only&status&q&limit&offset` | List; each document carries `folder_name`. `root_only=true` = Unfiled; `status=verified` for downstream |
| `GET /documents/{id}` | Status, extraction progress, pages |
| `PATCH /documents/{id}` | Rename (`filename`) and/or move (`folder_id`; `null` = Unfiled, in no folder) |
| `DELETE /documents/{id}` | Delete with its files and review. Refused (`409`) while it is being extracted or once it has verified versions (audit trail) |
| `POST /documents/{id}/retry` | Extract a failed document again |
| `GET /documents/{id}/extraction` | Machine output: lines with boxes and raw confidence |
| `GET /documents/{id}/pages/{n}/image` | Page image the boxes refer to (`?variant=original` for the source) |
| `GET/PUT /documents/{id}/review` | The reviewer's draft (saved with a version; a stale version gets `409`) |
| `POST /documents/{id}/confirm` | Draft → next verified version (lines nobody touched are accepted) |
| `POST /documents/{id}/reopen` | Back to review; the next confirm makes a new version |
| `GET /documents/{id}/verified[/{version}]` | **The verified record** (contract below) |
| `GET /documents/{id}/export?version&format=json\|csv` | Download a verified version |

Errors always look like `{"error": {"code": "...", "message": "..."}}`. `code` is stable; `message` can be shown to users.

Document status: `uploaded → processing → needs_review → verified`, `failed` from processing (retry), and `verified → needs_review` on reopen.

## For downstream components: the verified record (contract 0.1)

`GET /api/v1/documents/{id}/verified` returns the shape Component 03 proposed in
[Backend/Component-03/docs/c1_verified_record_contract.md](../Component-03/docs/c1_verified_record_contract.md):

```json
{
  "document_id": "6f1c…", "version": 2, "based_on_run_id": "a91e…",
  "confirmed_by": null, "confirmed_at": "2026-10-20T09:00:00+00:00",
  "lines": [
    {"line_id": "6d2a…", "page": 1, "sequence": 4, "text": "Total debits 1,250,000",
     "confidence": 0.41, "box": [40, 320, 140, 335], "provenance": "paddleocr",
     "escalated": null, "human_action": "edited"}
  ]
}
```

- Every line was reviewed by a person: `human_action` is `accepted`, `edited` or `added`. Deleted lines are left out.
- `confidence` is the engine's **raw** score, kept for analysis; it is `null` for lines a person added. It is not a probability.
- `box` is `[x1, y1, x2, y2]` in pixels of the page image from `/pages/{n}/image`.
- Versions are immutable. Find verified documents with `GET /documents?status=verified`.
- `confirmed_by` stays `null` until authentication exists.

## Tests

```powershell
uv run pytest -q                          # temporary SQLite database
uv run ruff check .
```

To run the same tests on PostgreSQL, set the variable **in the shell** (pytest does not read `.env`) to an **empty throwaway** database; its tables are dropped and recreated for every test:

```powershell
$env:NOMOS_TEST_DATABASE_URL = "postgresql+psycopg://postgres:PASSWORD@localhost:5432/nomos_test"
uv run pytest -q
```

Frontend tests (from `Frontend/`): `npm test`, and `npm run test:e2e` against a running backend (use `NOMOS_ENGINE=replay`).

## Troubleshooting

| Symptom | Cause |
|---|---|
| The Library says "Component 01 is not configured" | `VITE_C1_BASE` is not set in `Frontend/.env`; restart `npm run dev` after setting it |
| Browser shows "Cannot reach the server" but `/health` works | CORS: the frontend's origin is not in `NOMOS_CORS_ORIGINS` (default allows `localhost:5173` and `127.0.0.1:5173`) |
| Errors about a missing column or table | Migrations not applied: `uv run alembic upgrade head` |
| Boxes do not sit on the text | With `replay` this is expected on any document other than the sample. With `paddle`, the viewer warns when the image is not the size the boxes were measured on |
| PaddleOCR errors mentioning oneDNN / PIR on Windows | Handled inside the engine (oneDNN is off by default); avoid `smoke_ocr.py --mkldnn`, which turns it on |

## Layout

```text
app/
  api/v1/        routes: documents, folders, review (drafts, confirm, verified), export, health
  core/          settings (.env)
  db/            SQLAlchemy models; migrations live in alembic/
  jobs/          background worker (one extraction at a time)
  schemas/       API models
  services/
    ingestion/   file → page images (type detection, PDF rendering, limits)
    ocr/         engine interface, PaddleOCR wrapper; replay.py (dev engine)
    review/      drafts and confirmation (corrections log, verified versions)
    export/      verified record → contract (JSON/CSV)
    storage/     files: local disk (local.py) or S3 / Garage (s3.py), chosen in factory.py
scripts/smoke_ocr.py   run one file through ingestion + OCR from the command line
scripts/copy_store_to_s3.py   copy the local file store into the bucket before switching to s3
tests/                 pytest (SQLite by default)
```
