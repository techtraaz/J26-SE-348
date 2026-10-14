from app.schemas.case import AuditCase, AuditDocument
from app.services import orchestrator
from app.services.kg_client import KGClient


def test_full_case_pending_review():
    case = AuditCase(case_id="CASE-TV", docs=[
        AuditDocument(doc_id="BS26", case_id="CASE-TV", doc_type="balance_sheet",
                      period_year=2026, fields={"assets": 40000, "liabilities": 30000, "capital": 20000}),
        AuditDocument(doc_id="INV1", case_id="CASE-TV", doc_type="invoice",
                      period_year=2026, parent_doc_id="BS26",
                      fields={"amount": 250000}),
    ])
    res = orchestrator.run_case(case, KGClient())
    assert res.status == "pending_auditor_review"
    assert len(res.findings) >= 2  # equation + policy limit
    assert len(res.trace) == 5  # 5 agents each leave a trace
    # version grows, old kept by caller
    res2 = orchestrator.run_case(case, KGClient())
    assert res2.version == res.version + 1
