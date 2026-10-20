import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.services import c1_review, intake, llm, orchestrator
from app.services.c1_review import C1Input, ReviewedDocument
from app.services.field_mapper import Line, map_document
from app.services.llm.providers import LLMError
from tests.test_copilot import FakeLLM

SAMPLES = {p.stem: json.loads(p.read_text(encoding="utf-8"))
           for p in (Path(__file__).resolve().parents[1] / "eval" / "field_mapping").glob("*.json")}
client = TestClient(app)


@pytest.fixture
def fake_llm():
    def use(reply):
        provider = FakeLLM(reply)
        llm.use_provider(provider)
        return provider
    yield use
    llm.use_provider(None)


def preview(kg, name, **extra):
    return c1_review.preview("CASE-X", [C1Input.model_validate({**SAMPLES[name]["input"], **extra})], kg)[0]


def fields_of(p):
    return {f["field"]: f["value"] for f in p["fields"]}


# --- reading lines --------------------------------------------------------------------

@pytest.mark.parametrize("name", ["invoice_tax", "balance_sheet_columns", "trial_balance_verified"])
def test_rules_read_the_samples(kg, name):
    p = preview(kg, name)
    expected = SAMPLES[name]["expected"]
    assert fields_of(p) == expected["fields"]
    assert p["doc_type"] == expected["doc_type"]
    assert p["suggestions"]["period_year"]["value"] == expected["period_year"]
    assert p["missing_fields"] == [] and not p["llm"]["used"]


def test_grand_total_wins_over_sub_total_and_line_items(kg):
    amount = next(f for f in preview(kg, "invoice_tax")["fields"] if f["field"] == "amount")
    assert amount["line"]["text"].startswith("Grand Total") and amount["label"] == "grand total"
    assert {a["value"] for a in amount["alternatives"]} == {150000.0}


def test_same_row_values_take_the_current_year_column(kg):
    total = next(f for f in preview(kg, "balance_sheet_columns")["fields"] if f["field"] == "total_assets")
    assert total["value"] == 180000.0 and total["label_line"]["text"] == "Total assets"


def test_absent_optional_inputs_are_reported_not_guessed(kg, fake_llm):
    provider = fake_llm({"picks": []})
    p = preview(kg, "invoice_tax")
    assert {"rule_id": "CHK-005", "missing": ["cash_out", "asset_in"]} in p["rules_not_runnable"]
    assert provider.calls == []  # nothing required was missing, so no LLM call


def test_dates_ids_and_heading_years_are_not_amounts():
    lines = [Line(f"p1#{i}", 1, i, t, 0.9, None, "ocr", False) for i, t in enumerate(
        ["RECEIPT", "Ref: INV-00123", "20/03/2026 10:42", "2026  2025", "No.45 Main Street"])]
    from app.services.kg_client import MockKGClient
    m = map_document(lines, "receipt", MockKGClient(), use_llm=False)
    assert m.unmapped == [] and m.missing == ["amount"]


# --- the LLM fallback ---------------------------------------------------------------------

def test_llm_picks_a_line_and_code_reads_its_value(kg, fake_llm):
    provider = fake_llm({"picks": SAMPLES["receipt_unusual_label"]["llm_picks"]})
    p = preview(kg, "receipt_unusual_label")
    amount = next(f for f in p["fields"] if f["field"] == "amount")
    assert amount["value"] == 4500.0 and amount["method"] == "llm" and amount["needs_confirmation"]
    assert amount["confidence"] == config.UNCONFIRMED_MAPPING_CONFIDENCE
    schema = provider.calls[0][2]
    pick = schema["$defs"]["Pick"]["properties"]

    def choices(prop):  # one allowed value is written as "const", several as "enum"
        return prop.get("enum") or [prop["const"]]
    assert choices(pick["field"]) == ["amount"] and choices(pick["line_id"]) == ["p1#5"]


@pytest.mark.parametrize("reply", [{"picks": [{"field": "amount", "line_id": "p1#1"}]},  # not offered
                                   {"picks": [{"field": "total_assets", "line_id": "p1#5"}]},  # not wanted
                                   "no json", LLMError("timeout")])
def test_llm_cannot_invent_lines_or_fields(kg, fake_llm, reply):
    fake_llm(reply)
    p = preview(kg, "receipt_unusual_label")
    assert "amount" not in fields_of(p) and p["llm"]["error"] and p["missing_fields"] == ["amount"]


# --- confirming the review ---------------------------------------------------------------------

def confirm(kg, name, fields, **extra):
    body = {**SAMPLES[name]["input"], "doc_type": SAMPLES[name]["expected"]["doc_type"],
            "period_year": SAMPLES[name]["expected"]["period_year"], "fields": fields, **extra}
    return c1_review.confirm_case("CASE-X", [ReviewedDocument.model_validate(body)], kg)


def test_confirm_sets_confidence_by_how_each_value_was_read(kg):
    out = confirm(kg, "invoice_tax", [{"field": "amount", "line_id": "p1#10"},
                                      {"field": "purchase_basis", "line_id": "p1#11"}])
    d = out["case"]["docs"][0]
    assert d["fields"] == {"amount": 177000.0, "purchase_basis": "credit"}
    assert d["confidences"]["amount"] == 0.62  # raw OCR score of the line (machine extraction)
    assert d["methods"]["amount"] == "c1:paddleocr:p1#10|c3:rules"
    assert d["source"] == {"component": "c1", "document_id": "c1-inv-001", "run_id": "run-c1-inv-001",
                           "verified_version": None, "confirmed_by": None}
    assert any("machine extraction" in i for i in out["issues"])  # REV-008


def test_unconfirmed_ai_match_is_capped_and_flagged(kg):
    out = confirm(kg, "receipt_unusual_label", [{"field": "amount", "line_id": "p1#5"}])
    d = out["case"]["docs"][0]
    assert d["confidences"]["amount"] == config.UNCONFIRMED_MAPPING_CONFIDENCE
    assert d["methods"]["amount"].endswith("c3:unconfirmed")
    assert any("matched to its line by AI and not confirmed" in i for i in out["issues"])
    confirmed = confirm(kg, "receipt_unusual_label", [{"field": "amount", "line_id": "p1#5", "confirmed": True}])
    assert confirmed["case"]["docs"][0]["confidences"]["amount"] == 0.88


def test_verified_record_values_count_as_confirmed(kg):
    out = confirm(kg, "trial_balance_verified", [{"field": "total_debits", "line_id": "L4"},
                                                 {"field": "total_credits", "line_id": "L6"}])
    d = out["case"]["docs"][0]
    assert d["confidences"] == {"total_debits": 1.0, "total_credits": 1.0}  # raw 0.41 was human-checked
    assert d["methods"]["total_debits"] == "c1-verified-v2:L4|c3:rules"
    assert d["source"]["verified_version"] == 2 and d["source"]["confirmed_by"] == "auditor.nimal"
    assert not any("machine extraction" in i for i in out["issues"])


def test_reviewer_typed_value_is_human(kg):
    out = confirm(kg, "invoice_tax", [{"field": "amount", "line_id": "p1#10", "value": "Rs. 175,000"}])
    d = out["case"]["docs"][0]
    assert d["fields"]["amount"] == 175000.0 and d["confidences"]["amount"] == 1.0
    assert d["methods"]["amount"].endswith("c3:human")


@pytest.mark.parametrize("fields", [
    [{"field": "made_up_field", "line_id": "p1#10"}],          # not a known field name
    [{"field": "amount", "line_id": "p1#99"}],                 # line not in the record
    [{"field": "amount", "line_id": "p1#1"}],                  # line holds no amount
    [{"field": "amount"}],                                     # neither a line nor a value
    [{"field": "amount", "line_id": "p1#10"}, {"field": "amount", "line_id": "p1#8"}],
])
def test_confirm_rejects_bad_decisions(kg, fields):
    with pytest.raises(intake.IntakeError):
        confirm(kg, "invoice_tax", fields)


def test_confirmed_documents_audit_with_their_source(kg, store):
    out = confirm(kg, "invoice_tax", [{"field": "amount", "line_id": "p1#10"},
                                      {"field": "purchase_basis", "line_id": "p1#11"}])
    result = orchestrator.run_case(intake.normalize_case(out["case"]), kg, store=store)
    pol = next(f for f in result.findings if f.rule_id == "POL-07")
    assert pol.confidence == 0.62
    assert "source c1-inv-001: C1 machine extraction, not human-verified" in pol.reasoning_chain
    assert any(f.rule_id == "REV-008" for f in result.findings)


# --- API ------------------------------------------------------------------------------------

def test_api_preview_then_confirm():
    body = {"case_id": "API-R", "documents": [SAMPLES["invoice_tax"]["input"]]}
    p = client.post("/audit/intake/c1/preview", json=body).json()["documents"][0]
    assert p["document_id"] == "c1-inv-001" and not p["human_verified"]
    decisions = [{"field": f["field"], "line_id": f["line"]["line_id"]} for f in p["fields"]]
    confirmed = client.post("/audit/intake/c1/confirm", json={"case_id": "API-R", "documents": [
        {**SAMPLES["invoice_tax"]["input"], "doc_type": p["doc_type"], "period_year": 2026,
         "fields": decisions}]})
    assert confirmed.status_code == 200
    assert confirmed.json()["case"]["docs"][0]["fields"]["amount"] == 177000.0
    bad = client.post("/audit/intake/c1/confirm", json={"case_id": "API-R", "documents": [
        {**SAMPLES["invoice_tax"]["input"], "period_year": 2026, "fields": [{"field": "x", "line_id": "p1#1"}]}]})
    assert bad.status_code == 422
    unfinished = {"case_id": "API-R", "documents": [{"extraction": {
        "document_id": "d", "run": {"status": "running"}, "regions": []}}]}
    assert client.post("/audit/intake/c1/preview", json=unfinished).status_code == 422


# --- C1's real contract 0.1 (Backend/Component-01/app/schemas/review.py) ----------------

C1_CONTRACT_01 = {  # as GET /api/v1/documents/{id}/verified returns it, plus the export's tag
    "schema_version": "0.1",
    "document_id": "6f1c2a9e-3b7d-4c1e-9f0a-2d5b8e7c4a11", "version": 2,
    "based_on_run_id": "a91e7d3c-5f2b-4e8a-b1c6-9d0f3e2a7b55", "confirmed_by": None,
    "confirmed_at": "2026-10-20T09:00:00+00:00",
    "lines": [
        {"line_id": "0b6f0a51-1c2d-4e3f-8a9b-0c1d2e3f4a5b", "page": 1, "sequence": 1, "text": "TAX INVOICE",
         "confidence": 0.99, "box": [250, 80, 400, 100], "provenance": "paddleocr", "escalated": None,
         "human_action": "accepted"},
        {"line_id": "1c7a1b62-2d3e-4f40-9b0c-1d2e3f4a5b6c", "page": 1, "sequence": 2, "text": "Date: 12/03/2026",
         "confidence": 0.98, "box": [420, 110, 560, 125], "provenance": "paddleocr", "escalated": None,
         "human_action": "accepted"},
        {"line_id": "2d8b2c73-3e4f-4051-8c1d-2e3f4a5b6c7d", "page": 1, "sequence": 3,
         "text": "Grand Total Rs. 177,000.00", "confidence": 0.41, "box": [380, 255, 560, 270],
         "provenance": "paddleocr", "escalated": None, "human_action": "edited"},
        {"line_id": "3e9c3d84-4f50-4162-9d2e-3f4a5b6c7d8e", "page": 1, "sequence": 4,
         "text": "Payment Method: Credit", "confidence": None, "box": [40, 300, 260, 315],
         "provenance": "human", "escalated": None, "human_action": "added"},
    ],
}


def test_c1_contract_01_flows_through_review_and_audit(kg, store):
    p = c1_review.preview("C1-REAL", [C1Input.model_validate({"verified": C1_CONTRACT_01})], kg)[0]
    assert p["human_verified"] and p["doc_type"] == "invoice"
    assert p["suggestions"]["period_year"]["value"] == 2026
    assert fields_of(p) == {"amount": 177000.0, "purchase_basis": "credit"}

    out = c1_review.confirm_case("C1-REAL", [ReviewedDocument.model_validate({
        "verified": C1_CONTRACT_01, "doc_type": "invoice", "period_year": 2026,
        "fields": [{"field": f["field"], "line_id": f["line"]["line_id"]} for f in p["fields"]]})], kg)
    d = out["case"]["docs"][0]
    assert d["doc_id"] == C1_CONTRACT_01["document_id"]  # C1's id is the doc id everywhere
    assert d["confidences"] == {"amount": 1.0, "purchase_basis": 1.0}  # verified: raw 0.41 does not count
    assert d["source"]["verified_version"] == 2
    assert not any("machine extraction" in i for i in out["issues"])

    result = orchestrator.run_case(intake.normalize_case(out["case"]), kg, store=store)
    pol = next(f for f in result.findings if f.rule_id == "POL-07")
    assert any("C1 verified record v2" in s for s in pol.reasoning_chain)
