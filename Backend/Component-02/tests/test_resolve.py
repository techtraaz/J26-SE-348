import pytest

from app.construction.context import SeedReader
from app.construction.documents import LoadedDocument, Page
from app.construction.llm import FakeLLM
from app.construction.pipeline import KGPipeline
from app.construction.resolve import section_id, similarity, slug
from app.construction.validate import expression_items

PAGE = """Measurement of inventories

9  Inventories shall be measured at the lower of cost and net realisable
value.

40A  [Deleted]

41  An entity shall disclose the carrying amount of inventories pledged as security
for liabilities (see LKAS 37 and LKAS 1.54)."""

ANSWERS = {
    "Paragraph: 9\n": {
        "is_normative": True,
        "requirements": [{"text": "Measure inventories at the lower of cost and net realisable value",
                          "type": "measurement", "obligation": "shall",
                          "applies_to": ["inventories"]}],
        "definitions": [{"term": "Net realisable value", "text": "Selling price less costs"}],
        "equations": [{"name": "Lower of cost and NRV",
                       "expression": "inventories == min(inventory_cost, inventory_nrv)"}],
    },
    "Paragraph: 41\n": {
        "is_normative": True,
        "requirements": [{"text": "Disclose the carrying amount of inventories pledged as security",
                          "type": "disclosure", "obligation": "shall",
                          "applies_to": ["inventories", "balance_sheet"]}],
        "definitions": [{"term": "Pledged inventories", "text": "Inventories given as security"}],
        "references": [{"target": "LKAS 37"}, {"target": "LKAS 1.54"}],
        "equations": [{"name": "Pledged part", "expression": "inventories >= inventory_cost - inventory_nrv"}],
        "proposals": [{"label": "Risk", "name": "Pledged asset risk", "reason": "not covered"}],
    },
}


def _doc():
    return LoadedDocument(file="LKAS_02_Inventories.pdf", code="LKAS 2", source="pdf",
                          pages=[Page(5, PAGE)])


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, query, **params):
        self.calls.append((query, params))
        return []

    def rows(self, label):
        return [row for q, p in self.calls if f"MERGE (n:{label} " in q for row in p["rows"]]

    def rels(self, rel_type):
        return [(r["a"], r["b"]) for q, p in self.calls if f"[r:{rel_type}]" in q for r in p["rows"]]


@pytest.fixture(scope="module")
def run():
    rec = Recorder()
    result = KGPipeline(FakeLLM(ANSWERS), SeedReader(), run_write=rec).run(_doc())
    return result, rec


def test_plan_is_valid_and_written(run):
    result, _rec = run
    assert result.plan_errors == []
    assert result.written["Section"] == 3 and result.written["SourceChunk"] == 3


def test_seeded_requirement_is_matched_not_duplicated(run):
    result, rec = run
    new_ids = {r["key"] for r in rec.rows("Requirement")}
    assert "LKAS 2:9#R1" not in new_ids
    assert ("LKAS 2:9#R1", "LKAS 2:9") in rec.rels("EXTRACTED_FROM")
    assert "LKAS 2:41#R1" in new_ids
    assert result.matched["Requirement"] == 1 and result.created["Requirement"] == 1


def test_definitions_and_equations_match_by_term_and_expression(run):
    _result, rec = run
    assert ("LKAS 2:9", "DEF:nrv") in rec.rels("DEFINES")
    assert {r["key"] for r in rec.rows("Definition")} == {"DEF:pledged_inventories"}
    assert ("EQ-017", "LKAS 2:9") in rec.rels("EXTRACTED_FROM")
    assert {r["key"] for r in rec.rows("Equation")} == {"EQX-LKAS 2:41#1"}


def test_new_requirement_links_to_codes_and_references(run):
    _, rec = run
    applies = rec.rels("APPLIES_TO")
    assert ("LKAS 2:41#R1", "inventories") in applies
    assert ("LKAS 2:41#R1", "balance_sheet") in applies
    refers = set(rec.rels("REFERS_TO"))
    assert ("LKAS 2:41", "LKAS 37") in refers and ("LKAS 2:41", "LKAS 1:54") in refers


def test_sections_get_verbatim_text_and_chunks_get_embeddings(run):
    _, rec = run
    sections = {r["key"]: r["props"] for r in rec.rows("Section")}
    assert sections["LKAS 2:9"]["text"].startswith("9  Inventories shall be measured")
    assert sections["LKAS 2:9"]["source"] == "LKAS_02_Inventories.pdf"
    chunks = {r["key"]: r["props"] for r in rec.rows("SourceChunk")}
    assert len(chunks["LKAS 2:41"]["embedding"]) == 768 and chunks["LKAS 2:41"]["page"] == 5


def test_extracted_facts_have_lower_confidence(run):
    _, rec = run
    req = next(r["props"] for r in rec.rows("Requirement") if r["key"] == "LKAS 2:41#R1")
    assert req["confidence"] == 0.8 and req["source"] == "LKAS_02_Inventories.pdf"


def test_proposals_are_collected(run):
    result, _ = run
    assert {"chunk": "LKAS 2:41", "label": "Risk", "name": "Pledged asset risk",
            "reason": "not covered"} in result.proposals


def test_dry_run_writes_nothing():
    result = KGPipeline(FakeLLM(ANSWERS), SeedReader()).run(_doc())
    assert result.written == {} and result.plan_errors == []
    assert result.created["Requirement"] == 1


def test_helpers():
    assert section_id("LKAS 39:AG8#2") == "LKAS 39:AG8"
    assert section_id("LKAS 2:9") == "LKAS 2:9"
    assert slug("Net realisable value") == "net_realisable_value"
    assert similarity("Measure inventories at lower of cost and NRV",
                      "Inventories measured at the lower of cost and NRV") >= 0.5
    assert similarity("Disclose pledged inventories", "Measure at cost") == 0
    assert expression_items("gross_profit == revenue - cost_of_sales") == [
        ("lhs", "gross_profit", 1), ("rhs", "revenue", 1), ("rhs", "cost_of_sales", -1)]
    assert expression_items("inventories <= min(inventory_cost, inventory_nrv)") == [
        ("lhs", "inventories", 1), ("rhs", "inventory_cost", 1), ("rhs", "inventory_nrv", 1)]
