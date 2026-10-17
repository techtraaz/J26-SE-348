import re
from collections import Counter
from itertools import pairwise
from pathlib import Path
from statistics import mean, median

from pypdf import PdfReader

from app.construction.documents import LoadedDocument, Page
from app.schemas.extraction import ExtractionResult

_FILE_CODE = re.compile(r"^(CF|LKAS|SLFRS|SLAuS)(?:_(\d+))?_")
_NOISE = re.compile(r"^[\W_]*$")


def code_from_filename(name: str) -> str | None:
    m = _FILE_CODE.match(name)
    if not m:
        return None
    family, num = m.groups()
    return family if family == "CF" else f"{family} {int(num)}"


def _running_lines(pages: list[list[str]], min_share: float = 0.3) -> set[str]:
    """Lines that repeat at the top or bottom of many pages (headers, footers)."""
    edges = Counter()
    for lines in pages:
        kept = [ln.strip() for ln in lines if ln.strip()]
        edges.update(set(kept[:2] + kept[-2:]))
    limit = max(2, int(len(pages) * min_share))
    return {line for line, n in edges.items() if n >= limit}


def clean_pages(raw: list[str]) -> list[str]:
    split = [text.splitlines() for text in raw]
    running = _running_lines(split)
    cleaned = []
    for lines in split:
        keep = [ln.rstrip() for ln in lines
                if ln.strip() not in running and not _NOISE.match(ln.strip())
                or not ln.strip()]
        text = "\n".join(keep)
        text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        cleaned.append(text.strip())
    return cleaned


def load_pdf(path: Path) -> LoadedDocument:
    reader = PdfReader(path)
    raw = [page.extract_text() or "" for page in reader.pages]
    pages = [Page(number=i + 1, text=text) for i, text in enumerate(clean_pages(raw))]
    return LoadedDocument(file=path.name, code=code_from_filename(path.name),
                          source="pdf", pages=pages)


def _ocr_page_text(lines) -> str:
    if not lines:
        return ""
    ordered = sorted(lines, key=lambda ln: (ln.box[1], ln.box[0]))
    heights = [ln.box[3] - ln.box[1] for ln in ordered]
    gap_limit = 1.5 * max(median(heights), 1)
    out = [ordered[0].text]
    for prev, line in pairwise(ordered):
        if line.box[1] - prev.box[3] > gap_limit:
            out.append("")
        out.append(line.text)
    return "\n".join(out)


def load_extraction(result: ExtractionResult, file: str) -> LoadedDocument:
    """Component 01 OCR output to the same page format as a text PDF."""
    pages = []
    for p in sorted(result.pages, key=lambda p: p.page_number):
        conf = mean(ln.confidence for ln in p.lines) if p.lines else None
        pages.append(Page(number=p.page_number, text=_ocr_page_text(p.lines), confidence=conf))
    return LoadedDocument(file=file, code=code_from_filename(file), source="ocr", pages=pages)
