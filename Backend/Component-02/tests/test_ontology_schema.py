import copy

import pytest
import yaml

from app.ontology.model import SCHEMA_PATH, load_ontology, parse_ontology


@pytest.fixture
def raw():
    return yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_schema_loads():
    onto = load_ontology()
    assert onto.version == 1
    assert {"regulatory", "reporting", "audit", "evidence", "provenance"} == set(onto.layers)
    assert "Standard" in onto.labels_in_layer("regulatory")


def test_check_rule_matches_component_03_fields():
    props = load_ontology().node("CheckRule").properties
    assert {"rule_id", "name", "expression", "severity"} <= set(props)


def test_has_relationship():
    onto = load_ontology()
    assert onto.has_relationship("BELONGS_TO", "Standard", "Framework")
    assert not onto.has_relationship("BELONGS_TO", "Framework", "Standard")
    assert not onto.has_relationship("UNKNOWN", "Standard", "Framework")


def test_amendment_can_change_a_paragraph():
    assert load_ontology().has_relationship("AMENDS", "Amendment", "Section")


def test_line_item_presentation_keeps_section():
    rel = load_ontology().relationships["PRESENTED_IN"]
    assert "section" in rel.properties


def test_equation_links_to_statement_and_items():
    onto = load_ontology()
    assert "kind" in onto.node("Equation").required
    assert onto.has_relationship("HOLDS_IN", "Equation", "FinancialStatement")
    assert onto.has_relationship("USES", "Equation", "LineItem")


def test_rejects_unknown_label_in_relationship(raw):
    bad = copy.deepcopy(raw)
    bad["relationships"]["BELONGS_TO"]["to"] = ["Nope"]
    with pytest.raises(ValueError, match="unknown node label"):
        parse_ontology(bad)


def test_rejects_key_not_in_properties(raw):
    bad = copy.deepcopy(raw)
    bad["nodes"]["Standard"]["key"] = "missing"
    with pytest.raises(ValueError, match="key 'missing'"):
        parse_ontology(bad)


def test_rejects_unsupported_type(raw):
    bad = copy.deepcopy(raw)
    bad["nodes"]["Standard"]["properties"]["code"] = "text"
    with pytest.raises(ValueError, match="unsupported property types"):
        parse_ontology(bad)
