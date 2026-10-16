import pytest

from app.construction.classify import classify_document
from app.construction.context import SeedReader, base_context
from app.construction.documents import Chunk, LoadedDocument, Page
from app.construction.llm import FakeLLM, LLMError
from app.construction.pipeline import KGPipeline
from app.construction.schema import ChunkExtraction, ExtractionContext
from app.construction.validate import parse_reference, validate_chunk

LKAS2_PAGE = """Measurement of inventories

9  Inventories shall be measured at the lower of cost and net realisable
value.

40A  [Deleted]

41  An entity shall disclose the carrying amount of inventories pledged as security
for liabilities (see LKAS 37 Provisions)."""

LKAS2_9 = {
    "is_normative": True,
    "requirements": [{"text": "Inventories shall be measured at the lower of cost and NRV",
                      "type": "measurement", "obligation": "shall",
                      "applies_to": ["inventories", "made_up_code"]}],
    "equations": [{"name": "Lower of cost and NRV",
                   "expression": "inventories == min(inventory_cost, inventory_nrv)"}],
}


def _doc(text, code="LKAS 2", file="LKAS_02_Inventories.pdf"):
    return LoadedDocument(file=file, code=code, source="pdf", pages=[Page(1, text)])


@pytest.fixture(scope="module")
def reader():
    return SeedReader()


def test_seed_reader_gives_codes_and_known_facts(reader):
    ctx = base_context(reader)
    assert "inventories" in ctx.line_items and "balance_sheet" in ctx.document_types
    snap = reader.snapshot("LKAS 2")
    assert any("LKAS 2:9#R1" in k for k in snap.known("LKAS 2:9"))
    assert "definition Net realisable value" in snap.known("LKAS 2:6")
    assert snap.definitions["net realisable value"] == "DEF:nrv"
    assert snap.code_labels["balance_sheet"] == "DocumentType"


def test_pipeline_extracts_and_validates(reader):
    llm = FakeLLM({"Paragraph: 9\n": LKAS2_9})
    result = KGPipeline(llm, reader).run(_doc(LKAS2_PAGE))
    assert result.kind == "standard"
    by_id = {r.chunk.id: r for r in result.results}
    r9 = by_id["LKAS 2:9"]
    assert r9.extraction.requirements[0].applies_to == ["inventories"]
    assert len(r9.extraction.equations) == 1
    assert any(i.kind == "applies_to" and i.action == "changed" for i in r9.issues)
    assert "LKAS 2:40A" in result.skipped
    assert "Already in the graph" in llm.calls[0]


def test_client_documents_skip_the_llm(reader):
    llm = FakeLLM()
    doc = _doc("Tax Invoice No 0042\n\nTotal Rs. 250,000", code=None, file="inv_0042.pdf")
    result = KGPipeline(llm, reader).run(doc)
    assert result.kind == "client_document" and result.results == [] and llm.calls == []


def test_max_chunks_limits_llm_calls(reader):
    llm = FakeLLM()
    result = KGPipeline(llm, reader, max_chunks=1).run(_doc(LKAS2_PAGE))
    assert len(llm.calls) == 1 and "LKAS 2:41" in result.skipped


def test_llm_failure_is_recorded_not_raised(reader):
    class Broken(FakeLLM):
        def extract(self, *a, **k):
            raise LLMError("server down")

    result = KGPipeline(Broken(), reader).run(_doc(LKAS2_PAGE))
    assert set(result.errors) == {"LKAS 2:9", "LKAS 2:41"}
    assert result.results == []


def test_pipeline_diagram(reader):
    diagram = KGPipeline(FakeLLM(), reader).mermaid()
    for node in ("chunk", "classify", "retrieve_context", "extract", "validate"):
        assert node in diagram


def test_classify_document():
    assert classify_document(_doc("Sri Lanka Accounting Standard LKAS 2")) == "standard"
    assert classify_document(_doc("Disclosure Initiative (Amendments to LKAS 7)")) == "amendment"
    contents = "SLFRS 9 Financial Instruments " + "x " * 200 + "consequential amendments to LKAS 39"
    assert classify_document(_doc(contents, code="SLFRS 9")) == "standard"
    assert classify_document(_doc("Companies Act, No. 7 of 2007", code=None)) == "legislation"
    assert classify_document(_doc("hello", code=None)) == "unknown"


def test_parse_reference():
    codes = {"LKAS 1", "LKAS 37", "SLFRS 9"}
    assert parse_reference("LKAS 37", codes).standard == "LKAS 37"
    assert parse_reference("LKAS 1.25", codes).section == "LKAS 1:25"
    assert parse_reference("paragraph 81A of LKAS 1", codes).standard == "LKAS 1"
    assert parse_reference("LKAS 1 paragraph 81A", codes).section == "LKAS 1:81A"
    assert parse_reference("the Conceptual Framework", codes).standard == "CF"
    assert parse_reference("IFRS 99", codes).standard is None


def _chunk(text="9  Inventories shall be measured at the lower of cost and NRV."):
    return Chunk(id="LKAS 2:9", file="f.pdf", page=1, text=text, number="9")


def test_validate_drops_equation_with_unknown_items_and_proposes_them():
    ext = ChunkExtraction(equations=[{"name": "nrv", "expression": "nrv == price - selling_cost"}])
    out = validate_chunk(_chunk(), ext, ExtractionContext(line_items=["inventories"]), set())
    assert out.extraction.equations == []
    assert {p.name for p in out.extraction.proposals} == {"nrv", "price", "selling_cost"}


def test_validate_flags_obligation_mismatch_and_dedupes():
    req = {"text": "An entity shall disclose the cost formula", "type": "disclosure",
           "obligation": "may"}
    ext = ChunkExtraction(requirements=[req, req])
    out = validate_chunk(_chunk(), ext, ExtractionContext(), set())
    assert len(out.extraction.requirements) == 1
    kinds = {(i.kind, i.action) for i in out.issues}
    assert ("obligation", "warning") in kinds and ("requirement", "dropped") in kinds
    assert out.extraction.is_normative
