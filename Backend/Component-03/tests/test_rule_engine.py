"""Planted-error tests from Captain's examples."""
from app.schemas.case import AuditCase, AuditDocument
from app.schemas.findings import Finding
from app.services import rule_engine


def test_finding_defaults_pending_review():
    f = Finding(finding_id="F1", rule_id="CHK-001", category="ledger",
                severity="high", message="x")
    assert f.review_status == "pending_review"


def test_tv_wrong_side_equation_breaks():
    # TV 10000 bought with cash but booked wrong: assets low, equation breaks
    doc = AuditDocument(doc_id="BS1", case_id="C1", doc_type="balance_sheet",
                        period_year=2026,
                        fields={"assets": 40000, "liabilities": 30000, "capital": 20000})
    out = rule_engine.check_accounting_equation(doc)
    assert len(out) == 1 and out[0].rule_id == "CHK-001"


def test_amount_mismatch_parent_child():
    parent = AuditDocument(doc_id="BS1", case_id="C1", doc_type="balance_sheet",
                           period_year=2026, fields={"amount": 10000})
    child = AuditDocument(doc_id="INV1", case_id="C1", doc_type="invoice",
                          period_year=2026, parent_doc_id="BS1", fields={"amount": 5000})
    case = AuditCase(case_id="C1", docs=[parent, child])
    out = rule_engine.check_parent_amount_match(case)
    assert len(out) == 1 and out[0].rule_id == "CHK-003"


def test_cash_fraud_pattern():
    doc = AuditDocument(doc_id="INV9", case_id="C1", doc_type="invoice",
                        period_year=2026,
                        fields={"cash_out": 10000, "purchase_basis": "credit", "asset_in": 0})
    case = AuditCase(case_id="C1", docs=[doc])
    out = rule_engine.check_cash_without_asset(case)
    assert len(out) == 1 and out[0].category == "possible_fraud"


def test_equation_finding_inherits_lowest_source_confidence():
    doc = AuditDocument(doc_id="BS1", case_id="C1", doc_type="balance_sheet",
                        period_year=2026,
                        fields={"assets": 40000, "liabilities": 30000, "capital": 20000},
                        confidences={"assets": 0.42, "liabilities": 0.9, "capital": 0.8})
    out = rule_engine.check_accounting_equation(doc)
    assert len(out) == 1
    assert out[0].confidence == 0.42


def test_equation_confidence_defaults_to_one_when_unknown():
    doc = AuditDocument(doc_id="BS1", case_id="C1", doc_type="balance_sheet",
                        period_year=2026,
                        fields={"assets": 40000, "liabilities": 30000, "capital": 20000})
    assert rule_engine.check_accounting_equation(doc)[0].confidence == 1.0


def test_parent_match_uses_lowest_of_both_docs():
    parent = AuditDocument(doc_id="BS1", case_id="C1", doc_type="balance_sheet",
                           period_year=2026, fields={"amount": 10000},
                           confidences={"amount": 0.95})
    child = AuditDocument(doc_id="INV1", case_id="C1", doc_type="invoice",
                          period_year=2026, parent_doc_id="BS1", fields={"amount": 5000},
                          confidences={"amount": 0.42})
    out = rule_engine.check_parent_amount_match(AuditCase(case_id="C1", docs=[parent, child]))
    assert len(out) == 1 and out[0].confidence == 0.42


def test_low_confidence_is_rev001_review_not_a_violation():
    doc = AuditDocument(doc_id="BS1", case_id="C1", doc_type="balance_sheet",
                        period_year=2026,
                        fields={"assets": 50000, "liabilities": 30000, "capital": 20000},
                        confidences={"assets": 0.42})
    out = rule_engine.check_required_fields(doc)
    review = [f for f in out if f.rule_id == "REV-001"]
    assert len(review) == 1
    assert review[0].review_status == "needs_more_evidence"
    assert review[0].confidence == 0.42
    assert all(f.rule_id != "CHK-006" for f in out)
