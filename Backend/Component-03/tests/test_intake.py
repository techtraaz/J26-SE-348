import pytest

from app.services.intake import IntakeError, from_c1, normalize_case, parse_number
from tests.conftest import doc


@pytest.mark.parametrize("raw,out", [
    ("250,000", 250000.0), ("Rs. 10,000.00", 10000.0), ("LKR 5", 5.0), ("125000", 125000.0),
    ("(1,000)", -1000.0), ("1,23", "1,23"), ("12,34,567", "12,34,567"), ("abc", "abc"), (7, 7)])
def test_parse_number(raw, out):
    assert parse_number(raw) == out


def test_normalize_parses_only_numeric_fields():
    case = normalize_case({"case_id": "C", "docs": [doc("I", "Invoice", {
        "amount": "Rs. 1,000", "invoice_no": "00123"})]})
    d = case.docs[0]
    assert d.doc_type == "invoice" and d.fields == {"amount": 1000.0, "invoice_no": "00123"}


@pytest.mark.parametrize("payload", [
    {"case_id": "bad id!", "docs": []},
    {"case_id": "C", "docs": [doc("A", "invoice", {}), doc("A", "invoice", {})]},
    {"case_id": "C", "docs": [{"doc_id": "A", "fields": {}}]},  # no period_year
    {"case_id": "C", "docs": [doc("A", "invoice", {}, year=True)]},
    {"case_id": "C", "docs": [doc("A", "invoice", {}, confidences={"amount": "high"})]},
    {"case_id": "C", "docs": [doc("A", "invoice", {}, parent_doc_id="A")]},
    {"case_id": "C", "docs": ["not a doc"]},
])
def test_bad_intake_raises(payload):
    with pytest.raises(IntakeError):
        normalize_case(payload)


def _region(seq, text, key=None, conf=0.9):
    return {"sequence": seq, "page_number": 1, "text": text, "confidence": conf,
            "provenance": "paddleocr", "field_key": key}


def test_from_c1_maps_field_regions():
    case, unmapped = from_c1("C", [{
        "doc_type": "invoice", "period_year": 2026,
        "extraction": {"document_id": "INV-1", "run": {"status": "succeeded"}, "regions": [
            _region(1, "Rs. 125,000.00", "amount", 0.93), _region(2, "Thank you"),
            _region(3, "credit", "purchase_basis", 0.7)]}}])
    d = case.docs[0]
    assert d.doc_id == "INV-1" and d.fields == {"amount": 125000.0, "purchase_basis": "credit"}
    assert d.confidences == {"amount": 0.93, "purchase_basis": 0.7}
    assert d.methods["amount"] == "paddleocr" and unmapped == {"INV-1": 1}


def test_from_c1_keeps_conflicting_values_at_lower_confidence():
    case, _ = from_c1("C", [{"doc_type": "invoice", "period_year": 2026, "extraction": {
        "document_id": "I", "run": {"status": "succeeded"},
        "regions": [_region(1, "100", "amount", 0.9), _region(2, "700", "amount", 0.6)]}}])
    assert case.docs[0].fields["amount"] == ["100", "700"]
    assert case.docs[0].confidences["amount"] == 0.6


def test_from_c1_rejects_unfinished_run():
    with pytest.raises(IntakeError):
        from_c1("C", [{"doc_type": "invoice", "period_year": 2026, "extraction": {
            "document_id": "I", "run": {"status": "running"}, "regions": []}}])
