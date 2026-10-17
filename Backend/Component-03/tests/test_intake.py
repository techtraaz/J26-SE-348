"""Step 5: canonical intake validates + normalizes case JSON at the C3 door."""
import pytest

from app.schemas.canonical import ExtractionResult
from app.services import intake


def _valid_payload():
    return {"case_id": "CASE-INT", "docs": [
        {"doc_id": "BS1", "doc_type": "balance_sheet", "period_year": 2026,
         "fields": {"assets": 40000, "liabilities": 30000, "capital": 20000},
         "confidences": {"assets": 0.42}, "methods": {"assets": "ocr"}},
        {"doc_id": "INV1", "doc_type": "invoice", "period_year": 2026,
         "parent_doc_id": "BS1", "fields": {"amount": 10000}},
    ]}


def _extraction():
    return ExtractionResult(
        engine={"name": "paddle", "version": "1.0", "settings": {}},
        pages=[{"page_number": 1, "width": 100, "height": 200, "elapsed_ms": 5.0,
                "lines": [{"text": "assets 40000", "confidence": 0.9,
                           "box": (0, 0, 10, 10), "polygon": [(0, 0), (10, 0), (10, 10), (0, 10)]}]}])


def test_normalize_case_assigns_owner_and_clamps_confidence():
    case = intake.normalize_case(_valid_payload())
    assert case.case_id == "CASE-INT"
    assert all(d.case_id == "CASE-INT" for d in case.docs)
    assert case.docs[0].confidences["assets"] == 0.42


def test_bad_case_id_rejected():
    with pytest.raises(intake.IntakeError):
        intake.normalize_case({"case_id": "bad; DROP", "docs": []})


def test_duplicate_doc_id_rejected():
    payload = _valid_payload()
    payload["docs"].append(dict(payload["docs"][0]))
    with pytest.raises(intake.IntakeError, match="duplicate"):
        intake.normalize_case(payload)


def test_non_numeric_confidence_rejected():
    payload = _valid_payload()
    payload["docs"][0]["confidences"] = {"assets": "high"}
    with pytest.raises(intake.IntakeError, match="not a number"):
        intake.normalize_case(payload)


def test_bad_year_rejected():
    payload = _valid_payload()
    payload["docs"][0]["period_year"] = 12345
    with pytest.raises(intake.IntakeError, match="period_year"):
        intake.normalize_case(payload)


def test_confidence_out_of_range_is_clamped():
    payload = _valid_payload()
    payload["docs"][0]["confidences"] = {"assets": 1.8, "capital": -0.3}
    case = intake.normalize_case(payload)
    assert case.docs[0].confidences == {"assets": 1.0, "capital": 0.0}


def test_validate_case_flags_parent_and_unsupported_type():
    payload = _valid_payload()
    payload["docs"][1]["parent_doc_id"] = "MISSING"
    payload["docs"][1]["doc_type"] = "bank_statement"
    issues = intake.validate_case(intake.normalize_case(payload))
    assert any("parent_doc_id" in i for i in issues)
    assert any("not supported" in i for i in issues)


def test_from_extraction_bridges_pages_to_documents():
    case = intake.from_extraction(_extraction(), "CASE-EX", [
        {"page_number": 1, "doc_id": "INV1", "doc_type": "invoice",
         "period_year": 2026, "fields": {"amount": 10000}}])
    assert case.docs[0].methods == {"amount": "ocr"}
    assert case.docs[0].fields["amount"] == 10000


def test_from_extraction_unknown_page_rejected():
    with pytest.raises(intake.IntakeError, match="not in extraction"):
        intake.from_extraction(_extraction(), "CASE-EX", [
            {"page_number": 99, "doc_id": "INV1", "doc_type": "invoice"}])


def test_intake_endpoint_ok_and_rejected():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    ok = client.post("/audit/intake", json=_valid_payload())
    assert ok.status_code == 200
    assert ok.json()["contract_version"] == intake.INTAKE_VERSION
    bad = client.post("/audit/intake", json={"case_id": "x;y", "docs": []})
    assert bad.status_code == 422
