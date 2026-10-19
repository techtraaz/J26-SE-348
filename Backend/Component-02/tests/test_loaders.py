from app.construction.loaders import (
    clean_pages,
    code_from_filename,
    code_from_title,
    load_extraction,
)
from app.schemas.extraction import EngineInfo, ExtractionResult, OCRLine, PageResult


def test_code_from_filename():
    assert code_from_filename("LKAS_02_Inventories.pdf") == "LKAS 2"
    assert code_from_filename("SLFRS_15_Revenue_from_Contracts.pdf") == "SLFRS 15"
    assert code_from_filename("CF_Conceptual_Framework_for_Financial_Reporting.pdf") == "CF"
    assert code_from_filename("invoice_0042.pdf") is None


def test_code_from_title():
    assert code_from_title("Sri Lanka Accounting Standard – LKAS 18\n\nRevenue") == "LKAS 18"
    assert code_from_title("Sri Lanka Accounting Standard - SLFRS 09 Financial Instruments") == "SLFRS 9"
    assert code_from_title("! ! The Conceptual Framework for Financial Reporting") == "CF"
    # a company policy that only cites a standard is not that standard
    assert code_from_title("Procurement Policy\nAssets are recorded as per LKAS 16.") is None


def test_running_headers_and_noise_removed():
    pages = [f"LKAS 2\n!\n{n}  Paragraph text {n}.\nLKAS 2" for n in range(1, 6)]
    cleaned = clean_pages(pages)
    assert all("LKAS 2" not in p and "!" not in p for p in cleaned)
    assert cleaned[2] == "3  Paragraph text 3."


def test_footnote_blocks_removed():
    page = ("9  Revenue shall be measured at fair value.1\n\n" + "!" * 40
            + '1"!See also SIC-31 Revenue.\nsecond footnote line!\n\n10  Next paragraph.')
    cleaned = clean_pages([page, "11  a", "12  b"])[0]
    assert "SIC-31" not in cleaned and "!" not in cleaned
    assert cleaned == "9  Revenue shall be measured at fair value.1\n\n10  Next paragraph."


def test_hyphenated_words_joined():
    pages = ["29  net realis-\nable value", "30  other", "31  text"]
    assert clean_pages(pages)[0] == "29  net realisable value"


def _line(text, y, conf=0.9):
    return OCRLine(text=text, confidence=conf, box=(10, y, 300, y + 20),
                   polygon=[(10, y), (300, y), (300, y + 20), (10, y + 20)])


def test_ocr_result_becomes_pages_with_paragraph_breaks():
    result = ExtractionResult(
        engine=EngineInfo(name="paddle", version="3", settings={}),
        pages=[PageResult(page_number=1, width=600, height=800, elapsed_ms=5.0, lines=[
            _line("9  Inventories shall be measured at the lower", 100, 0.9),
            _line("of cost and net realisable value.", 122, 0.7),
            _line("10  The cost of inventories shall comprise", 200, 0.8),
        ])],
    )
    doc = load_extraction(result, "LKAS_02_scan.pdf")
    assert doc.source == "ocr" and doc.code == "LKAS 2"
    assert doc.pages[0].text.split("\n\n")[1].startswith("10  The cost")
    assert abs(doc.pages[0].confidence - 0.8) < 1e-9
