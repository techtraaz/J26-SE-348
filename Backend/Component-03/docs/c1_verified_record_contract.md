# Proposed C1 endpoint: verified records for downstream components

**From:** Component 03 (Amarasinghe) · **To:** Component 01 (Jayanath) · **Status:** implemented in C1 as contract 0.1 (`GET /api/v1/documents/{id}/verified`, `app/services/export/contract_v1.py`); C3 tests it in `tests/test_c1_review.py`

C1's `verified_records` table is described as "the immutable confirmed version
that downstream reads", but no endpoint returns it yet. C3 currently reads the
machine output (`GET /api/v1/documents/{id}/extraction`) and marks every audit
built on it as *not human-verified*. This proposes the endpoint C3 needs.
C3 is already built to it: as soon as it exists, the Library uses it, with no
change in C3.

## Endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/api/v1/documents/{id}/verified` | the latest verified version |
| GET | `/api/v1/documents/{id}/verified/{version}` | one version (versions are 1, 2, 3, …) |

`404` when the document has no verified record yet. C3 then falls back to `/extraction`.

## Reply

```json
{
  "document_id": "6f1c…",
  "version": 2,
  "based_on_run_id": "a91e…",
  "confirmed_by": "auditor.nimal",
  "confirmed_at": "2026-04-02T09:00:00+00:00",
  "lines": [
    {"line_id": "6d2a…", "page": 1, "sequence": 4, "text": "Total debits 1,250,000",
     "confidence": 0.41, "box": [40, 320, 140, 335], "provenance": "paddleocr",
     "escalated": false, "human_action": "edited"}
  ]
}
```

| Field | Source in C1 | Notes |
|---|---|---|
| `document_id`, `version`, `based_on_run_id`, `confirmed_by`, `confirmed_at` | `verified_records` | as stored |
| `lines[]` | `verified_records.data` | the confirmed lines, in reading order |
| `line_id` | region id, or a new id for added lines | stable within the version |
| `page`, `sequence`, `box` | `regions` / `pages` | `box` = `[x1, y1, x2, y2]` in OCR-space pixels of that page |
| `text` | confirmed text | after the human's edits |
| `confidence` | `regions.confidence` | the machine's raw score, kept for C1's calibration analysis; `null` for added lines |
| `provenance`, `escalated` | `regions` | `"human"` for lines the reviewer added |
| `human_action` | `corrections` | `untouched` \| `accepted` \| `edited` \| `added` |

## How C3 uses it

- `document_id` is the `doc_id` in C3 cases (and should be the `doc_id` of C2's `SourceDocument`).
- Values from a verified record count as confirmed by a person: C3 does not raise low-confidence
  review items for them. Raw scores are kept, not used.
- C3 records the `version`, `based_on_run_id` and `confirmed_by` in every audit's
  `AuditDocument.source`, so each finding traces back to the exact verified version.
- No field template is needed: C3 maps lines to fields itself (labels matched against C2's
  field names), and a person reviews the mapping in the Library before auditing.

C3's copy of this shape: `Backend/Component-03/app/schemas/c1.py` (`C1VerifiedRecord`).
