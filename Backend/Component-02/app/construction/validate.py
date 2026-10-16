import re
from dataclasses import dataclass, field

from app.construction.documents import Chunk
from app.construction.schema import ChunkExtraction, ExtractionContext, ProposedConcept

_FUNCS = {"min", "max", "abs"}
_IDENT = re.compile(r"\b[a-z_][a-z0-9_]*\b(?!\s*\()")
_REF = re.compile(
    r"\b(LKAS|SLFRS|SLAuS)\s*(\d+)(?:\s*(?:\.|,?\s*paragraphs?|\bpara\.?)\s*([A-Z]{0,2}\d+(?:\.\d+)*[A-Z]?))?",
    re.IGNORECASE)


@dataclass
class Issue:
    chunk_id: str
    kind: str
    detail: str
    action: str  # "dropped", "changed" or "warning"


@dataclass
class Reference:
    raw: str
    standard: str | None = None
    section: str | None = None


@dataclass
class ValidatedChunk:
    chunk: Chunk
    extraction: ChunkExtraction
    references: list[Reference] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


def parse_reference(raw: str, standard_codes: set[str]) -> Reference:
    if "conceptual framework" in raw.lower():
        return Reference(raw, "CF")
    m = _REF.search(raw)
    if not m:
        return Reference(raw)
    family = {"lkas": "LKAS", "slfrs": "SLFRS", "slaus": "SLAuS"}[m.group(1).lower()]
    code = f"{family} {int(m.group(2))}"
    if code not in standard_codes:
        return Reference(raw)
    return Reference(raw, code, f"{code}:{m.group(3)}" if m.group(3) else None)


def validate_chunk(chunk: Chunk, ext: ChunkExtraction, ctx: ExtractionContext,
                   standard_codes: set[str]) -> ValidatedChunk:
    issues: list[Issue] = []
    allowed = set(ctx.line_items) | set(ctx.account_classes) | set(ctx.document_types)
    line_items = set(ctx.line_items)

    def issue(kind, detail, action):
        issues.append(Issue(chunk.id, kind, detail, action))

    requirements, seen = [], set()
    for req in ext.requirements:
        text = " ".join(req.text.split())
        if not text or text.lower() in seen:
            issue("requirement", f"empty or repeated: {text[:60]!r}", "dropped")
            continue
        seen.add(text.lower())
        unknown = [c for c in req.applies_to if c not in allowed]
        if unknown:
            issue("applies_to", f"unknown codes removed {unknown}", "changed")
        said = next((w for w in ("shall", "should", "may") if re.search(rf"\b{w}\b", text.lower())),
                    None)
        if said and said != req.obligation:
            issue("obligation", f"marked '{req.obligation}' but says '{said}': {text[:60]!r}",
                  "warning")
        requirements.append(req.model_copy(update={
            "text": text, "applies_to": [c for c in req.applies_to if c in allowed]}))

    definitions, terms = [], set()
    for d in ext.definitions:
        if not d.term.strip() or not d.text.strip() or d.term.lower() in terms:
            issue("definition", f"empty or repeated term {d.term!r}", "dropped")
            continue
        terms.add(d.term.lower())
        definitions.append(d)

    equations, proposals = [], list(ext.proposals)
    for eq in ext.equations:
        names = {n for n in _IDENT.findall(eq.expression) if n not in _FUNCS}
        unknown = sorted(names - line_items)
        if not re.search(r"==|<=|>=|<|>", eq.expression):
            issue("equation", f"not a comparison: {eq.expression!r}", "dropped")
        elif unknown:
            issue("equation", f"unknown line items {unknown} in {eq.expression!r}", "dropped")
            proposals += [ProposedConcept(label="LineItem", name=n,
                                          reason=f"used in equation '{eq.name}' ({chunk.id})")
                          for n in unknown]
        else:
            equations.append(eq)

    references = []
    for r in ext.references:
        ref = parse_reference(r.target, standard_codes)
        if ref.standard is None:
            issue("reference", f"not a known standard: {r.target!r}", "warning")
        references.append(ref)

    clean = ChunkExtraction(
        is_normative=ext.is_normative or bool(requirements or definitions),
        requirements=requirements, definitions=definitions, references=ext.references,
        equations=equations, proposals=proposals)
    return ValidatedChunk(chunk, clean, references, issues)
