import re

from app.construction.documents import Chunk, LoadedDocument

# "54", "81A", "4.4", "4.1.1", "OB2", "QC11", "AG8", "B5.4.2"; followed by text starting in capitals
_PARA = re.compile(r"^(?P<num>(?:[A-Z]{1,2})?\d{1,3}(?:\.\d{1,3}){0,2}[A-Z]{0,2})\s+(?P<rest>[A-Z\[(].*)",
                   re.DOTALL)
_NUM_PARTS = re.compile(r"^([A-Z]{0,2})(\d{1,3})(?:\.(\d{1,3}))?(?:\.(\d{1,3}))?([A-Z]{0,2})$")
_HEADING_END = (".", ";", ":", ",")
MAX_CHARS = 2500
# "[Deleted]" and "[This paragraph refers to amendments that are not yet effective ...]"
_PLACEHOLDER = re.compile(r"\[(?:deleted|th(?:is|ese) paragraphs? refers? to amendments[^\]]*)\]\.?",
                          re.IGNORECASE)


def _is_contents(text: str) -> bool:
    head = text[:300].upper()
    return "CONTENTS" in head


def _is_heading(block: str) -> bool:
    lines = block.splitlines()
    return (len(lines) <= 2 and len(block) <= 120 and not block.endswith(_HEADING_END)
            and not block.startswith("(") and not _PARA.match(block))


def _order(num: str) -> tuple[str, tuple]:
    prefix, major, minor, sub, suffix = _NUM_PARTS.match(num).groups()
    return prefix, (int(major), int(minor or 0), int(sub or 0), suffix)


# numbered examples inside a paragraph ("1 A machine cost 100") go back to an
# earlier number, so a paragraph must move forward within its series
def _is_next(num: str, last: dict) -> bool:
    prefix, order = _order(num)
    if prefix in last and order <= last[prefix]:
        return False
    last[prefix] = order
    return True


# "4.1 Classification of financial assets" heads paragraphs 4.1.1, 4.1.2 ...
def _is_numbered_heading(block: str, m: re.Match) -> bool:
    return ("." in m.group("num") and "\n" not in block and len(block) <= 120
            and not m.group("rest").startswith("[") and not block.endswith(_HEADING_END))


def _strip_placeholders(text: str) -> str:
    text = _PLACEHOLDER.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# what is left of "98C [Deleted] 98D–98G" is only paragraph numbers
def _has_words(text: str) -> bool:
    return any(len(w) > 2 for w in re.sub(r"[^A-Za-z]+", " ", text).split())


def _split_long(text: str, limit: int = MAX_CHARS) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for piece in re.split(r"(?<=[.;])\s+", text):
        if current and len(current) + len(piece) > limit:
            parts.append(current.strip())
            current = ""
        current += piece + " "
    if current.strip():
        parts.append(current.strip())
    return parts


def _blocks(doc: LoadedDocument):
    for page in doc.pages:
        if _is_contents(page.text):
            continue
        for block in re.split(r"\n\s*\n", page.text):
            block = block.strip()
            if block:
                yield page, block


def chunk_paragraphs(doc: LoadedDocument) -> list[Chunk]:
    """One chunk per numbered paragraph, keeping the heading it sits under.
    Deleted paragraphs are dropped, and so is the unnumbered intro of a known standard."""
    prefix = doc.code or doc.file
    paras: list[dict] = []
    heading = None
    last: dict = {}
    for page, block in _blocks(doc):
        m = _PARA.match(block)
        if m and _is_numbered_heading(block, m):
            heading = " ".join(block.split())
        elif m and (not paras or _is_next(m.group("num"), last)):
            if not paras:
                _is_next(m.group("num"), last)
            paras.append({"num": m.group("num"), "heading": heading, "page": page,
                          "text": block})
        elif _is_heading(block):
            heading = " ".join(block.split())
        elif paras:
            paras[-1]["text"] += "\n\n" + block
        else:
            paras.append({"num": "intro", "heading": heading, "page": page, "text": block})

    chunks, seen = [], {}
    for p in paras:
        if p["num"] == "intro" and doc.code:
            continue
        p["text"] = _strip_placeholders(p["text"])
        if not _has_words(p["text"].removeprefix(p["num"])):
            continue
        base = f"{prefix}:{p['num']}"
        seen[base] = seen.get(base, 0) + 1
        if seen[base] > 1:
            base = f"{base}#dup{seen[base]}"
        parts = _split_long(p["text"])
        for i, text in enumerate(parts, start=1):
            chunks.append(Chunk(
                id=base if len(parts) == 1 else f"{base}#{i}",
                file=doc.file, page=p["page"].number, text=text,
                number=None if p["num"] == "intro" else p["num"], heading=p["heading"],
                confidence=p["page"].confidence,
            ))
    return chunks


def chunk_by_size(doc: LoadedDocument, limit: int = MAX_CHARS) -> list[Chunk]:
    """Fallback for documents without numbered paragraphs."""
    chunks = []
    for page in doc.pages:
        for i, text in enumerate(_split_long(" ".join(page.text.split()), limit), start=1):
            chunks.append(Chunk(id=f"{doc.file}:p{page.number}#{i}", file=doc.file,
                                page=page.number, text=text, confidence=page.confidence))
    return chunks


# a known standard keeps its paragraphs even when short (a one page amendment);
# other documents need a few numbered paragraphs before we trust the numbering
def chunk_document(doc: LoadedDocument) -> list[Chunk]:
    chunks = chunk_paragraphs(doc)
    numbered = sum(1 for c in chunks if c.number)
    return chunks if numbered >= (1 if doc.code else 3) else chunk_by_size(doc)
