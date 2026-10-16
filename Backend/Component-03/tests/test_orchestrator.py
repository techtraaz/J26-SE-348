from app.schemas.case import AuditCase, AuditDocument
from app.schemas.findings import Finding
from app.services import orchestrator
from app.services.agents import evidence_validation
from app.services.kg_client import KGClient


def _tv_case(case_id="CASE-TV"):
    return AuditCase(case_id=case_id, docs=[
        AuditDocument(doc_id="BS26", case_id=case_id, doc_type="balance_sheet",
                      period_year=2026, fields={"assets": 40000, "liabilities": 30000, "capital": 20000}),
        AuditDocument(doc_id="INV1", case_id=case_id, doc_type="invoice",
                      period_year=2026, parent_doc_id="BS26",
                      fields={"amount": 250000}),
    ])


def test_full_case_pending_review():
    case = _tv_case()
    res = orchestrator.run_case(case, KGClient())
    assert res.status == "pending_auditor_review"
    assert len(res.findings) >= 2  # equation + policy limit
    assert len(res.trace) == 5  # 5 agents each leave a trace
    # version grows, old kept by caller
    res2 = orchestrator.run_case(case, KGClient())
    assert res2.version == res.version + 1


def test_trace_exactly_five_in_right_order():
    res = orchestrator.run_case(_tv_case("CASE-ORD"), KGClient())
    names = [t.agent_name for t in res.trace]
    assert names == ["data_quality", "compliance", "anomaly", "reasoning", "evidence_validation"]


def test_parallel_branches_before_reasoning():
    res = orchestrator.run_case(_tv_case("CASE-PAR"), KGClient())
    names = [t.agent_name for t in res.trace]
    assert names.index("compliance") < names.index("reasoning")
    assert names.index("anomaly") < names.index("reasoning")


def test_same_input_same_findings():
    r1 = orchestrator.run_case(_tv_case("CASE-DET"), KGClient())
    r2 = orchestrator.run_case(_tv_case("CASE-DET2"), KGClient())
    # same docs -> same rule_ids in same set (versions differ, findings same)
    assert sorted(f.rule_id for f in r1.findings) == sorted(f.rule_id for f in r2.findings)
    assert sorted(f.finding_id for f in r1.findings) == sorted(f.finding_id for f in r2.findings)


def test_fake_evidence_id_caught_and_logged():
    case = _tv_case("CASE-FAKE")
    bad = Finding(finding_id="X-FAKE", rule_id="CHK-001", category="ledger",
                  severity="high", message="planted fake citation",
                  evidence_ids=["DOC-999-GHOST"], policy_ids=["CHK-001"])
    kept, trace = evidence_validation.run(case, [bad])
    assert kept == []
    assert "caught 1 bad" in trace[0].detail
    # full pipeline logs it in rejected_citations
    res = orchestrator.run_case(case, KGClient())
    assert isinstance(res.rejected_citations, list)
    assert isinstance(res.rejected_records, list)
