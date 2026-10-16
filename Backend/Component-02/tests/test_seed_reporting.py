import re

import pytest

from app.ontology.seed import load_seed

FUNCS = {"min", "max", "abs"}

# copied from Component 03 rule_engine.py / mock_data.json
C03_RULES = {
    "CHK-001": {"name": "Accounting equation", "expression": "assets == liabilities + capital",
                "severity": "high"},
}
C03_RULE_IDS = {"CHK-001", "CHK-002", "CHK-003", "CHK-004", "CHK-005", "CHK-006"}


@pytest.fixture(scope="module")
def seed():
    return load_seed()


def _vars(expr):
    return {v for v in re.findall(r"\b[a-z_]+\b(?!\s*\()", expr) if v not in FUNCS}


def _rels(seed, rel_type, source_label):
    out = {}
    for r in seed.rels:
        if r.type == rel_type and r.source[0] == source_label:
            out.setdefault(r.source[1], set()).add(r.target[1])
    return out


@pytest.mark.parametrize("label", ["Equation", "Ratio"])
def test_uses_matches_expression(seed, label):
    uses = _rels(seed, "USES", label)
    for item in seed.nodes[label]:
        assert uses.get(item["code"]) == _vars(item["expression"]), item["code"]


def test_equation_signs_follow_expression(seed):
    signs = {r.target[1]: r.props["sign"] for r in seed.rels
             if r.type == "USES" and r.source == ("Equation", "EQ-005")}
    assert signs == {"gross_profit": 1, "revenue": 1, "cost_of_sales": -1}


def test_equations_cite_a_source_except_bookkeeping(seed):
    sourced = _rels(seed, "DERIVED_FROM", "Equation")
    for eq in seed.nodes["Equation"]:
        assert (eq["code"] in sourced) == (eq["kind"] != "bookkeeping"), eq["code"]


def test_component_03_rules_are_present_unchanged(seed):
    rules = {r["rule_id"]: r for r in seed.nodes["CheckRule"]}
    assert C03_RULE_IDS <= set(rules)
    for rule_id, expected in C03_RULES.items():
        assert {k: rules[rule_id][k] for k in expected} == expected
    assert any(p["rule_id"] == "POL-07" and p["limit"] == 100000 for p in seed.nodes["PolicyRule"])


def test_component_03_field_names_resolve_to_line_items(seed):
    names = {}
    for item in seed.nodes["LineItem"]:
        for name in [item["code"], *item.get("aliases", [])]:
            assert name not in names, f"{name} used by {names.get(name)} and {item['code']}"
            names[name] = item["code"]
    assert names["assets"] == "total_assets"
    assert names["liabilities"] == "total_liabilities"
    assert names["capital"] == "total_equity"
    assert names["debit_total"] == "total_debits"


def test_balance_sheet_check_rules_reach_c03_doc_type(seed):
    checks = {r.source[1] for r in seed.rels
              if r.type == "CHECKS_DOC_TYPE" and r.target == ("DocumentType", "balance_sheet")}
    assert "CHK-001" in checks
