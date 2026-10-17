from datetime import date

import pytest

from app.ontology.model import load_ontology
from app.ontology.seed import Rel, Seed, load_seed, parse_ref, validate, write


@pytest.fixture
def onto():
    return load_ontology()


def _seed(nodes, rels=()):
    s = Seed()
    for label, items in nodes.items():
        s.nodes[label].extend(items)
    s.rels.extend(rels)
    return s


def test_parse_ref_keeps_colons_in_key():
    assert parse_ref("Section:LKAS 1:54") == ("Section", "LKAS 1:54")


def test_committed_seed_is_valid(onto):
    seed = load_seed()
    assert validate(seed, onto) == []
    codes = {s["code"] for s in seed.nodes["Standard"]}
    assert {"CF", "LKAS 1", "LKAS 2", "LKAS 7", "LKAS 8", "LKAS 10", "SLFRS 15"} <= codes


def test_superseded_standards_have_a_replacement(onto):
    seed = load_seed()
    superseded = {s["code"] for s in seed.nodes["Standard"] if s["status"] == "superseded"}
    replaced = {r.target[1] for r in seed.rels if r.type == "SUPERSEDES"}
    assert superseded == replaced


def test_catches_unknown_property_and_missing_required(onto):
    seed = _seed({"Standard": [{"code": "X 1", "family": "LKAS", "colour": "red"}]})
    errors = validate(seed, onto)
    assert any("unknown property 'colour'" in e for e in errors)
    assert any("missing required ['title']" in e for e in errors)


def test_catches_wrong_type(onto):
    seed = _seed({"Standard": [{"code": "X 1", "title": "t", "family": "LKAS",
                                "effective_from": "2012-01-01"}]})
    assert any("should be date" in e for e in validate(seed, onto))


def test_catches_relationship_not_in_ontology(onto):
    seed = _seed(
        {"Standard": [{"code": "X 1", "title": "t", "family": "LKAS"}],
         "Framework": [{"code": "F", "name": "f"}]},
        [Rel("BELONGS_TO", ("Framework", "F"), ("Standard", "X 1"))],
    )
    assert any("not allowed by ontology" in e for e in validate(seed, onto))


def test_catches_dangling_reference(onto):
    seed = _seed(
        {"Standard": [{"code": "X 1", "title": "t", "family": "LKAS"}]},
        [Rel("BELONGS_TO", ("Standard", "X 1"), ("Framework", "NOPE"))],
    )
    assert any("Framework:NOPE not in seed" in e for e in validate(seed, onto))


def test_write_merges_by_key_and_groups_relationships(onto):
    seed = _seed(
        {"Standard": [{"code": "X 1", "title": "t", "family": "LKAS",
                       "effective_from": date(2012, 1, 1)}],
         "Framework": [{"code": "F", "name": "f"}]},
        [Rel("BELONGS_TO", ("Standard", "X 1"), ("Framework", "F"))],
    )
    calls = []
    counts = write(seed, onto, lambda q, **p: calls.append((q, p)) or [])
    assert counts == {"Standard": 1, "Framework": 1, "BELONGS_TO": 1}
    assert "MERGE (n:Standard {code: row.key})" in calls[0][0]
    assert "MERGE (a)-[r:BELONGS_TO]->(b)" in calls[2][0]
