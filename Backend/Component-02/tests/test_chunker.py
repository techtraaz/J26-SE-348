from app.construction.chunker import chunk_by_size, chunk_document, chunk_paragraphs
from app.construction.documents import LoadedDocument, Page


def _doc(*pages, code="LKAS 2"):
    return LoadedDocument(file="LKAS_02_Inventories.pdf", code=code, source="pdf",
                          pages=[Page(i + 1, t) for i, t in enumerate(pages)])


PAGE_1 = """CONTENTS
OBJECTIVE 1
SCOPE 2"""

PAGE_2 = """Sri Lanka Accounting Standard LKAS 2 Inventories is set out in paragraphs 1-40.

Objective

1  The objective of this Standard is to prescribe the accounting treatment
for inventories.

Measurement of inventories

9  Inventories shall be measured at the lower of cost and net realisable
value."""

PAGE_3 = """for example:

(a)  damaged items; and

11  The tax base of an asset is shown in these examples:

1  A machine cost 100. For tax purposes, depreciation of 30 has
already been deducted.

12  The cost of inventories shall comprise all costs of purchase.

40A  [Deleted]"""


def test_paragraph_ids_headings_and_pages():
    chunks = {c.id: c for c in chunk_paragraphs(_doc(PAGE_1, PAGE_2, PAGE_3))}
    assert chunks["LKAS 2:9"].heading == "Measurement of inventories"
    assert chunks["LKAS 2:9"].page == 2
    assert chunks["LKAS 2:1"].heading == "Objective"
    assert chunks["LKAS 2:intro"].number is None


def test_contents_page_is_skipped():
    ids = [c.id for c in chunk_paragraphs(_doc(PAGE_1, PAGE_2))]
    assert ids == ["LKAS 2:intro", "LKAS 2:1", "LKAS 2:9"]


def test_text_continues_across_pages():
    chunks = {c.id: c for c in chunk_paragraphs(_doc(PAGE_2, PAGE_3))}
    assert "(a)  damaged items" in chunks["LKAS 2:9"].text


def test_numbered_example_stays_inside_its_paragraph():
    chunks = {c.id: c for c in chunk_paragraphs(_doc(PAGE_2, PAGE_3))}
    assert "LKAS 2:1#dup2" not in chunks
    assert "A machine cost 100" in chunks["LKAS 2:11"].text
    assert "LKAS 2:12" in chunks
    assert "LKAS 2:40A" in chunks


def test_three_level_numbers_and_numbered_headings():
    page = """4.1 Classification of financial assets

4.1.1  Unless paragraph 4.1.5 applies, an entity shall classify financial assets.

4.1.2  A financial asset shall be measured at amortised cost.

B4.1.1  This appendix is an integral part of the Standard."""
    chunks = chunk_paragraphs(_doc(page, code="SLFRS 9"))
    assert [c.id for c in chunks] == ["SLFRS 9:4.1.1", "SLFRS 9:4.1.2", "SLFRS 9:B4.1.1"]
    assert chunks[0].heading == "4.1 Classification of financial assets"


def test_long_paragraph_is_split():
    long_para = "5  " + " ".join(["The entity shall disclose the amount."] * 200)
    chunks = chunk_paragraphs(_doc(long_para))
    assert len(chunks) > 1
    assert chunks[0].id == "LKAS 2:5#1" and all(len(c.text) <= 2600 for c in chunks)


def test_unnumbered_document_falls_back_to_size_chunks():
    doc = _doc("Invoice No 123\n\nCustomer ABC Ltd\n\nTotal Rs. 250,000", code=None)
    chunks = chunk_document(doc)
    assert chunks == chunk_by_size(doc)
    assert chunks[0].id == "LKAS_02_Inventories.pdf:p1#1"
