import pytest

from app.services.intake import IntakeError, normalize_case, parse_number
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


def test_source_is_validated_and_kept():
    case = normalize_case({"case_id": "C", "docs": [doc("I", "invoice", {"amount": 5}, source={
        "document_id": "c1-1", "run_id": "r1", "verified_version": 2, "confirmed_by": "nimal"})]})
    assert case.docs[0].source.human_verified and case.docs[0].source.verified_version == 2
    with pytest.raises(IntakeError):
        normalize_case({"case_id": "C", "docs": [doc("I", "invoice", {}, source={"run_id": "r1"})]})
