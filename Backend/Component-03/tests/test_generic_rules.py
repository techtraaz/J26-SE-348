"""Step 7: safe expression evaluator + KG-driven check rules in compliance."""
import pytest

from app.schemas.case import AuditCase, AuditDocument
from app.services import orchestrator, rule_engine
from app.services.expression import ExpressionError, evaluate
from app.services.kg_client import KGClient

# ── Safe evaluator ─────────────────────────────────────────────────────

def test_evaluate_arithmetic_and_tolerance():
    assert evaluate("assets == liabilities + capital",
                    {"assets": 50000, "liabilities": 30000, "capital": 20000}, 0.01)
    assert not evaluate("assets == liabilities + capital",
                        {"assets": 40000, "liabilities": 30000, "capital": 20000}, 0.01)
    assert evaluate("a == b", {"a": 100.0, "b": 100.005}, 0.01)
    assert not evaluate("a == b", {"a": 100.0, "b": 100.005}, 0.001)


def test_evaluate_ordering_and_chained():
    assert evaluate("assets > liabilities", {"assets": 10, "liabilities": 5})
    assert evaluate("0 <= a < 10", {"a": 5})
    assert not evaluate("0 <= a < 10", {"a": 10})


@pytest.mark.parametrize("expr", [
    "a.__class__", "__import__('os')", "open('x')", "a if a else 0",
    "assets", "1 + 2", "a == b == c if True else x", "lambda: 1",
])
def test_evaluator_rejects_unsafe_expressions(expr):
    with pytest.raises(ExpressionError):
        evaluate(expr, {"a": 1, "b": 2, "c": 3, "assets": 1})


def test_evaluator_rejects_unknown_input_and_bool_literal():
    with pytest.raises(ExpressionError, match="unknown input"):
        evaluate("assets == x", {"assets": 1})
    with pytest.raises(ExpressionError):
        evaluate("assets == True", {"assets": 1})


@pytest.mark.parametrize("expr", ["assets / liabilities == 1",
                                  "assets % liabilities == 1"])
def test_evaluator_reports_arithmetic_errors(expr):
    with pytest.raises(ExpressionError, match="arithmetic error"):
        evaluate(expr, {"assets": 10, "liabilities": 0})


# ── Rule runner ────────────────────────────────────────────────────────

def _bs(**fields):
    return AuditDocument(doc_id="BS1", case_id="C1", doc_type="balance_sheet",
                         period_year=2026, fields=fields)


def test_run_check_rules_fires_and_carries_confidence():
    doc = AuditDocument(doc_id="BS1", case_id="C1", doc_type="balance_sheet",
                        period_year=2026, fields={"assets": 100, "liabilities": 30000},
                        confidences={"assets": 0.42})
    rules = [{"rule_id": "CHK-900", "name": "assets cover liabilities",
              "expression": "assets >= liabilities", "inputs": ["assets", "liabilities"],
              "tolerance": 0.01, "severity": "high", "category": "ledger"}]
    out = rule_engine.run_check_rules(doc, rules)
    assert len(out) == 1 and out[0].rule_id == "CHK-900"
    assert out[0].confidence == 0.42
    assert out[0].category == "ledger" and out[0].severity == "high"


def test_run_check_rules_skips_missing_inputs():
    rules = [{"rule_id": "CHK-901", "expression": "assets == capital",
              "inputs": ["assets", "capital"], "category": "ledger"}]
    assert rule_engine.run_check_rules(_bs(assets=10), rules) == []


def test_run_check_rules_expression_error_is_visible():
    rules = [{"rule_id": "CHK-902", "expression": "assets ** 2",
              "inputs": ["assets"], "category": "ledger"}]
    out = rule_engine.run_check_rules(_bs(assets=10), rules)
    assert len(out) == 1 and out[0].finding_id.endswith("-expr")
    assert "could not be evaluated" in out[0].message


def test_run_check_rules_pass_is_silent():
    rules = [{"rule_id": "CHK-903", "expression": "assets == liabilities",
              "inputs": ["assets", "liabilities"], "category": "ledger"}]
    assert rule_engine.run_check_rules(_bs(assets=5, liabilities=5), rules) == []


# ── Integration through compliance ─────────────────────────────────────

class _RuleKG(KGClient):
    def get_rules(self, doc_type: str) -> list:
        return []

    def get_check_rules(self, doc_type: str) -> list:
        return [{"rule_id": "CHK-900", "name": "assets cover liabilities",
                 "expression": "assets >= liabilities", "inputs": ["assets", "liabilities"],
                 "tolerance": 0.01, "severity": "high", "category": "ledger"}]


def test_run_check_rules_division_by_zero_is_visible():
    rules = [{"rule_id": "CHK-904", "expression": "assets / liabilities == 1",
              "inputs": ["assets", "liabilities"], "category": "ledger"}]
    out = rule_engine.run_check_rules(_bs(assets=10, liabilities=0), rules)
    assert len(out) == 1 and out[0].finding_id.endswith("-expr")
    assert "could not be evaluated" in out[0].message


def test_compliance_records_skipped_generic_rules():
    from app.services.agents import compliance

    class _MissingInputKG(KGClient):
        def get_rules(self, doc_type: str) -> list:
            return []

        def get_check_rules(self, doc_type: str) -> list:
            return [{"rule_id": "CHK-905", "expression": "assets == capital",
                     "inputs": ["assets", "capital"], "category": "ledger"}]

    case = AuditCase(case_id="C1", docs=[_bs(assets=10)])
    findings, trace = compliance.run(case, _MissingInputKG())
    assert findings == []
    assert any(t.decision_type == "skip" and "CHK-905" in t.detail
               for t in trace)


def test_compliance_runs_generic_rules():
    case = AuditCase(case_id="CASE-GEN", docs=[
        AuditDocument(doc_id="BS1", case_id="CASE-GEN", doc_type="balance_sheet",
                      period_year=2026,
                      fields={"assets": 100, "liabilities": 30000, "capital": 0})])
    res = orchestrator.run_case(case, _RuleKG())
    assert any(f.rule_id == "CHK-900" for f in res.findings)


def test_generic_rule_does_not_duplicate_hardcoded_chk001():
    case = AuditCase(case_id="CASE-DEDUP", docs=[
        AuditDocument(doc_id="BS1", case_id="CASE-DEDUP", doc_type="balance_sheet",
                      period_year=2026,
                      fields={"assets": 40000, "liabilities": 30000, "capital": 20000})])
    res = orchestrator.run_case(case, KGClient())
    chk001 = [f for f in res.findings if f.rule_id == "CHK-001"]
    assert len(chk001) == 1
