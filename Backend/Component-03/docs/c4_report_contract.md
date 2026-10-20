# C3 → C4: audit record for the final report

Status: implemented in C3 (result `schema_version` 1). Owner: Component-03.

## Where the data is

MongoDB database `nomos_xai`, collection `c03_audit_results`. One document per
audit run, never overwritten:

- `_id` = `"<case_id>:v<version>"`, e.g. `"CASE-20261020-H3MN:v2"`. This is the
  **audit id**. A re-run of the same case is a new version with a new `_id`.
- Latest run of a case: `find({"case_id": X}).sort("version", -1).limit(1)`.

C4 builds the PDF from this record only. C3 makes every audit decision (findings,
verdict, score, recommendations) in code; the LLM writes only `narrative`.

## Stability promise

- Fields listed here are never renamed, removed or given a new meaning.
- New fields may be **added** at any time; ignore fields you do not know.
- If a breaking change is ever unavoidable, `schema_version` goes up (now `1`)
  and both teams agree first. Check it before reading a record.

## The fields C4 needs

| Need | Field | Content |
|---|---|---|
| Overall verdict | `verdict` | `clean` (no findings), `issues_found` (a rule failed), `needs_review` (no rule failed; items need the auditor), `not_auditable` (nothing could be checked) |
| Audit score | `score` | 0–100, or `null` when `not_auditable`. 100 minus 25 per high, 10 per medium, 3 per low rule finding and 2 per review item, never below 0 |
| Summary | `summary` | Always present, one sentence in a fixed shape, e.g. `2 documents audited; 2 rule checks: 2 failed (5 not run, inputs missing); 2 rule findings (2 high), 0 review items.` |
| Written summary | `narrative` | The LLM's summary for the auditor, or `null` (LLM off, or its text used a number not in the facts and was dropped). Optional decoration only |
| Recommendations | `recommendations[]` | One per finding, most severe first: `finding_id`, `rule_id`, `severity`, `text` (fixed wording per rule, from code) |
| How complete the check was | `coverage` | `rules_run`, `passed`, `failed`, `review`, `error`, `not_run` (inputs missing), `complete` (every applicable rule could be evaluated). Show "limited check" when `complete` is false |
| Values still needed | `open_questions[]` | One per rule that could not run for lack of values on its own document: `doc_id`, `doc_name`, `rule_id`, `rule_name`, `missing` (field names), `question` (plain text) |
| Documents used | `case.docs[]` | `doc_id` (C1's document id), `name` (file name), `doc_type`, `period_year`, `parent_doc_id` (the document it supports), `fields`, `confidences`, `source` (`component`, `document_id`, `verified_version`, `confirmed_by`) |
| Rules evaluated | `rules_applied[]` | Every KG rule run on every document, passed ones too (see below) |
| Findings | `findings[]` | `finding_id`, `rule_id`, `category`, `severity`, `message`, `evidence_ids`, `policy_ids` (cited standards, e.g. `CF:4.4`), `confidence`, `review_status`, `claims`, `reasoning_chain`, `evidence_validation` |
| Run facts | `case_id`, `version`, `status`, `kg_source`, `created_at`, `case.materiality` | `kg_source` `live` = rules from the live KG |

`REV-*` findings are review items (data problems for the auditor), never rule
violations; `CHK-*` / `POL-*` are rule findings.

### `rules_applied[]` (same facts and words as the live `rule_check` / `policy_check` steps)

| Field | Meaning |
|---|---|
| `kind` | `rule_check` (a KG check rule) or `policy_check` (a policy limit such as POL-07) |
| `rule_id`, `rule_name` | e.g. `CHK-001`, `Accounting equation` (a policy rule's text for `policy_check`) |
| `doc_id`, `doc_type` | the document it ran on (name: look up `case.docs`) |
| `outcome` | `passed`, `failed`, `review` (needs the auditor's confirmation), `skipped` (inputs missing), `error` (could not be evaluated) |
| `expression` | the rule, e.g. `assets == liabilities + capital`, or `amount <= 100000` for a limit |
| `values` | inputs used by name, e.g. `{"assets": 164673550.0, ...}` |
| `sides` | both sides of a comparison: `left`, `op`, `right`, `left_value`, `right_value`; `null` otherwise |
| `detail` | the calculation in words, e.g. `assets 164,673,550.00 vs liabilities + capital 152,611,400.00` |
| `reason` | why it was skipped, the error, or the finding's message when it failed |
| `limit`, `approvals_required`, `approvals_signed` | policy rules only |
| `compared_with` | for cross-document rules: `prior` / `child` / `parent` → doc id |
| `severity`, `below_materiality` | the finding's severity (or the rule's), and whether a case materiality lowered it |
| `missing_inputs` | for `skipped`: every input it lacked, e.g. `["cash_out", "purchase_basis", "asset_in"]` |
| `finding_id` | the finding it produced, or `null` |

**Verdict and coverage:** `clean` is given only when no finding exists **and** at least one
rule could be evaluated; when every applicable rule was skipped, the verdict is
`needs_review` and `score` is `null` (an unchecked case is never shown as clean).

## Report request: C3 → C4

When the user asks the Copilot to "generate the report", C3 sends:

```
POST {C4_URL}/report/generate
Content-Type: application/json

{"audit_id": "CASE-20261020-H3MN:v2", "case_id": "CASE-20261020-H3MN", "version": 2}
```

`C4_URL` is set in C3's `.env` (default `http://localhost:8004`). Use `audit_id`
(or `case_id` + `version`) to read exactly that record. Timeout: 120 s.

C4 replies `200` with at least:

```json
{"status": "report_ready", "download_url": "/report/download/<file>.pdf"}
```

`download_url` may be relative to `C4_URL` or absolute. C3 shows the link in the
chat. On an error reply, give `{"detail": "<why>"}`; C3 shows it to the user.

Until C4 serves `POST /report/generate`, C3 falls back to C4's current
`POST /report/generate/{case_id}` (no body).

## Example record (abridged: two documents, two failed rules)

```json
{
  "_id": "CASE-20261020-DEMO:v1",
  "case_id": "CASE-20261020-DEMO",
  "version": 1,
  "status": "pending_auditor_review",
  "kg_source": "live",
  "schema_version": 1,
  "verdict": "issues_found",
  "score": 50,
  "summary": "2 documents audited; 2 rule checks: 2 failed (5 not run, inputs missing); 2 rule findings (2 high), 0 review items.",
  "narrative": null,
  "recommendations": [
    {"finding_id": "d71db802-...-CHK-001", "rule_id": "CHK-001", "severity": "high",
     "text": "Reconcile the statement: find why total assets differ from liabilities plus equity (unposted or misclassified entries) and correct it."},
    {"finding_id": "08a3cbe1-...-POL-07", "rule_id": "POL-07", "severity": "high",
     "text": "Get the missing approval signed before payment, and record who approved it and when."}
  ],
  "findings": [
    {"finding_id": "d71db802-...-CHK-001", "rule_id": "CHK-001", "category": "ledger", "severity": "high",
     "message": "Accounting equation failed for 02_Statement_of_Financial_Position_Wk42_2026-10-18.pdf: assets == liabilities + capital is false (assets=164,673,550.00, liabilities=67,832,630.00, capital=84,778,770.00). Difference: 12,062,150.00.",
     "evidence_ids": ["d71db802-..."], "policy_ids": ["CF:4.4"], "confidence": 1.0,
     "review_status": "pending_review", "evidence_validation": "passed"}
  ],
  "rules_applied": [
    {"kind": "rule_check", "rule_id": "CHK-001", "rule_name": "Accounting equation",
     "doc_id": "d71db802-...", "doc_type": "balance_sheet", "agent": "compliance", "outcome": "failed",
     "expression": "assets == liabilities + capital",
     "values": {"assets": 164673550.0, "liabilities": 67832630.0, "capital": 84778770.0},
     "sides": {"left": "assets", "op": "==", "right": "liabilities + capital",
               "left_value": 164673550.0, "right_value": 152611400.0},
     "detail": "assets 164,673,550.00 vs liabilities + capital 152,611,400.00",
     "reason": "Accounting equation failed for 02_Statement_...pdf: ...", "finding_id": "d71db802-...-CHK-001"},
    {"kind": "policy_check", "rule_id": "POL-07", "rule_name": "Purchases above Rs. 100,000 need dual approval.",
     "doc_id": "08a3cbe1-...", "doc_type": "invoice", "outcome": "failed", "expression": "amount <= 100000",
     "values": {"amount": 636256.0}, "limit": 100000.0, "approvals_required": 2, "approvals_signed": 1.0,
     "detail": "amount 636,256.00 > limit 100,000.00; 1 of 2 approvals signed"},
    {"kind": "rule_check", "rule_id": "CHK-005", "doc_id": "08a3cbe1-...", "outcome": "skipped",
     "reason": "missing cash_out", "finding_id": null}
  ],
  "case": {
    "case_id": "CASE-20261020-DEMO", "materiality": null,
    "docs": [
      {"doc_id": "d71db802-...", "name": "02_Statement_of_Financial_Position_Wk42_2026-10-18.pdf",
       "doc_type": "balance_sheet", "period_year": 2026, "parent_doc_id": null,
       "fields": {"total_assets": 164673550, "total_liabilities": 67832630, "total_equity": 84778770},
       "source": {"component": "c1", "document_id": "d71db802-...", "verified_version": 1}},
      {"doc_id": "08a3cbe1-...", "name": "04_Tax_Invoice_COI-INV-26-1158.pdf", "doc_type": "invoice",
       "period_year": 2026, "parent_doc_id": null, "fields": {"amount": 636256, "approvals": 1},
       "source": {"component": "c1", "document_id": "08a3cbe1-...", "verified_version": 1}}
    ]
  },
  "trace": ["..."],
  "events_published": true,
  "created_at": "2026-10-20T14:27:53+00:00"
}
```
