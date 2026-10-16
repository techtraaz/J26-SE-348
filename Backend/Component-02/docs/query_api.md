# KG Query API (for Component 03)

Component 02 serves the audit knowledge graph over HTTP on port **8002**. Every endpoint below
is a fixed, parameterised query: agents never send Cypher, which matches
`ALLOW_FREE_CYPHER = False` in Component 03.

Interactive docs while the server runs: `http://localhost:8002/docs`.

## Switching from mock to live

Copy [`clients/kg_client_http.py`](../clients/kg_client_http.py) into Component 03 (standard
library only, no new dependency). It has the same methods and return shapes as
`app/services/kg_client.py`, so the agents do not change:

```python
from app.services.kg_client_http import HTTPKGClient

kg = HTTPKGClient("http://localhost:8002")   # instead of KGClient(mode="mock")
kg.get_check_rules("balance_sheet")
```

If the server is down the client raises `KGUnavailable`, so the caller can fall back to mock.

## Contract

| KGClient method | Endpoint | Returns |
|---|---|---|
| `get_rules(doc_type)` | `GET /query/rules/{doc_type}` | `[{rule_id, text, limit}]` |
| `get_check_rules(doc_type)` | `GET /query/check-rules/{doc_type}` | `[{rule_id, name, expression, severity, variables}]` |
| `get_evidence_chain(doc_id)` | `GET /query/evidence-chain/{doc_id}` | `[doc_id, ...linked ids]` |
| `get_postings(case_id)` | `GET /query/postings/{case_id}` | `[{entry_id, doc_id, doc_type, action, seq}]` |
| `get_period_totals(case_id, year)` | `GET /query/period-totals/{case_id}?year=` | `{assets, liabilities, capital, year}` |

`CHK-001` to `CHK-006` and `POL-07` are the same ids, names, expressions and severities as
`mock_data.json` and `rule_engine.py`.

**`variables`** is extra and safe to ignore. It tells you what each name in an expression
means, so the newer rules can be evaluated against document fields:

```json
{"rule_id": "CHK-001", "name": "Accounting equation", "expression": "assets == liabilities + capital",
 "severity": "high", "variables": [
   {"name": "assets", "line_item": "total_assets", "aliases": ["assets"]},
   {"name": "capital", "line_item": "total_equity", "aliases": ["capital", "equity"]}]}
```

`GET /query/fields` gives the full name map (`capital` → `total_equity`, `cogs` → `cost_of_sales`,
`debit_total` → `total_debits`).

**Not filled yet:** `get_postings` and `get_period_totals` return the same empty shapes as the
mock until the evidence ledger (Component 02, Phase 5) stores client documents and amounts.

## Explaining findings

`GET /query/rules/{rule_id}/explain` (client: `explain_rule`) returns the rule, the equation or
requirement it implements, assertions, risks, document types, **citations** (standard,
paragraph, heading, text) and a sentence that can go straight into a finding:

> CHK-011 Inventory not above NRV checks `inventories <= inventory_nrv`. Applies to
> balance_sheet. It implements EQ-017 Inventory at lower of cost and NRV
> (`inventories == min(inventory_cost, inventory_nrv)`). Source: LKAS 2 para 9 (Inventories,
> Measurement of inventories). Tests the Accuracy, valuation and allocation assertion(s).

## Lookups and search

| Endpoint | Client | Use |
|---|---|---|
| `GET /query/sections/{id}` | `get_section` | Paragraph text, requirements, definitions, amendments, page. Encode ids: `LKAS%202:9` |
| `GET /query/standards/{code}` | | Status, superseded by, amendments, what it governs |
| `GET /query/line-items/{code}` | | Code or alias: statement, class, governing standards, equations |
| `GET /query/equations?statement=&kind=` | | Equations with sources and check rules |
| `GET /query/definitions/{term}` | | Definition and where it is defined |
| `GET /query/search?q=&mode=&limit=&standard=` | `search` | Paragraphs by reference (`LKAS 2:9`), keyword, meaning or both (`hybrid`) |

Semantic search needs the real embedding model; until then `hybrid` returns keyword results
with a `note`.

## Errors

| Status | Meaning |
|---|---|
| 404 | Rule, section, standard or line item not found (the client returns `None` or the mock default) |
| 422 | Bad parameter, e.g. search query shorter than 2 characters |
| 503 | Neo4j not reachable |

## Read-only Cypher (people only)

`POST /query/cypher` with `{"query": "...", "params": {}}` is for debugging and demos. It runs
in a read transaction with a timeout and row cap, rejects writes and admin calls, and can be
turned off with `QUERY_CYPHER_ENABLED=false`. Agents should use the fixed endpoints.

## Checking it

```powershell
python -m scripts.smoke_query                              # in process, against Neo4j in .env
python -m scripts.smoke_query --base-url http://localhost:8002   # against a running server
```
