# C3 → C2: knowledge-graph additions requested

Status: requested 21 Oct 2026. Owner of the change: Component-02 (Alawaththa).
C3 reads everything below through the existing `/query/*` endpoints, so no new
endpoint is needed; only seed data (and the fields noted) change. C3 keeps working
without them: each item says what C3 does today.

## 1. Goods received note and purchase order line items (three-way match)

**Why:** a GRN carries quantities and dates, not money, so C3 reads nothing from it
today and the auditor gets a "no values were read" review item. The audit control
that uses a GRN is the three-way match: ordered (PO) = received (GRN) = billed
(invoice), and goods received before payment.

**Requested line items** (with aliases as on real documents):

| Code | Name | Aliases (examples) | Statement / document |
|---|---|---|---|
| `quantity_ordered` | Quantity ordered | ordered, qty ordered | purchase_order |
| `quantity_received` | Quantity received | received, qty received | goods_received_note |
| `quantity_accepted` | Quantity accepted | accepted, qty accepted | goods_received_note |
| `quantity_billed` | Quantity billed | qty, quantity | invoice |
| `po_number` | Purchase order number | PO number, PO no, customer PO | purchase_order, goods_received_note, invoice |
| `date_received` | Date received | received on, date of receipt | goods_received_note |

**Requested check rules** (CheckRule + CHECKS_DOC_TYPE + TESTS/ADDRESSES):

| Rule | Expression | Applies to | Severity | Tests / addresses |
|---|---|---|---|---|
| Quantity received matches order | `child.quantity_received == parent.quantity_ordered` | goods_received_note | medium | Occurrence, Completeness / misstatement due to error |
| Quantity billed not above accepted | `child.quantity_billed <= parent.quantity_accepted` | invoice | high | Occurrence / misstatement due to fraud |

The `child.` / `parent.` form is what C3's Anomaly agent already evaluates (as CHK-003),
using the "supports" link set in the case.

**Today in C3:** GRN kept as supporting evidence with REV-004; only CHK-003 (PO amount
= invoice amount) is checked.

## 2. `required_approvals` on policy rules

**Why:** C3 reads the number of approvals POL-07 needs from its text ("dual" = 2).
A number in the graph is exact and works for any wording or language.

**Requested:** `PolicyRule.required_approvals` (integer) returned by
`GET /query/rules/{doc_type}`, e.g. `{"rule_id": "POL-07", "limit": 100000.0, "required_approvals": 2, ...}`.
C3 already has the field in its copy of the reply shape and uses it when present.

## 3. A category on each check rule

**Why:** C3 decides which agent runs a rule and how the finding is labelled from a
table in its own config (`RULE_CATEGORY`), e.g. CHK-005 = possible_fraud. A new KG
rule gets the default category until C3's table is updated.

**Requested:** `CheckRule.category`, one of `arithmetic`, `ledger`, `compliance`,
`possible_fraud`, `format`, returned by `GET /query/check-rules/{doc_type}`.

## 4. Rules for documents that have none

**Why:** `purchase_order`, `goods_received_note`, `receipt`, `bank_statement`,
`fixed_asset_register` and `payroll` are accepted but have no rules, so only data
checks run on them. Suggested starting points (amounts already exist as line items):

| Document | Suggested rule |
|---|---|
| receipt | receipt amount matches the invoice it supports (`child.amount == parent.amount`) |
| bank_statement | closing balance ties to cash and cash equivalents on the SFP |
| payroll | total net pay ties to the payroll payment voucher |

## 5. Where each line item is presented

**Why:** some rules tie two statements together (e.g. CHK-009 closing cash on the cash
flow statement = cash on the SFP). On a statement alone, C3 cannot tell whether a
missing value belongs on this document or on another one, so it may ask the auditor
for a value the document does not show. `GET /query/line-items/{code}` already has
`presented_in`; please make sure it is filled for every line item, so C3 can ask
only for values the document should contain.
