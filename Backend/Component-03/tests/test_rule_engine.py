"""Planted-error tests from Captain's examples."""
from app.schemas.case import AuditCase, AuditDocument
from app.services import rule_engine


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
