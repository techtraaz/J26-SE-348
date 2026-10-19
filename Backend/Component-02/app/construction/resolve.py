import re
from collections import Counter
from dataclasses import dataclass, field

from app.construction.context import GraphSnapshot, norm_expr
from app.construction.documents import Chunk, LoadedDocument
from app.construction.validate import ValidatedChunk, expression_items
from app.ontology.seed import Rel, Seed

# extracted facts are less certain than seed data and PDF text
EXTRACTION_CONFIDENCE = 0.8
MATCH_THRESHOLD = 0.5
_STOP = {"the", "and", "for", "that", "this", "with", "are", "shall", "should", "may", "its",
         "entity", "from", "which", "any", "all", "not", "has", "have", "been", "when", "such"}
_SPLIT_SUFFIX = re.compile(r"#\d+$")


def section_id(chunk_id: str) -> str:
    return _SPLIT_SUFFIX.sub("", chunk_id)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in _STOP}


def similarity(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def slug(term: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", term.lower()).strip("_")


@dataclass
class Resolution:
    plan: Seed
    existing: dict[str, set]
    matched: Counter = field(default_factory=Counter)
    created: Counter = field(default_factory=Counter)
    proposals: list[dict] = field(default_factory=list)


class _Plan:
    def __init__(self):
        self.seed = Seed()
        self._nodes: dict[tuple[str, str], dict] = {}
        self._rels: set[tuple] = set()

    def node(self, label: str, key: str, props: dict) -> None:
        if (label, key) not in self._nodes:
            self._nodes[(label, key)] = props
            self.seed.nodes[label].append(props)

    def rel(self, rel_type: str, source: tuple[str, str], target: tuple[str, str],
            props: dict | None = None) -> None:
        if (rel_type, source, target) not in self._rels:
            self._rels.add((rel_type, source, target))
            self.seed.rels.append(Rel(rel_type, source, target, props or {}))


def _title(doc: LoadedDocument) -> str:
    """LKAS_42_Some_Title.pdf -> Some Title, falling back to the code."""
    stem = re.sub(r"^[A-Za-z]+_\d+_", "", doc.file.rsplit(".", 1)[0])
    return " ".join(stem.replace("_", " ").split()) or doc.code


def _confidence(chunk: Chunk, base: float) -> float:
    return round(base * (chunk.confidence if chunk.confidence is not None else 1.0), 3)


def resolve(doc: LoadedDocument, chunks: list[Chunk], results: list[ValidatedChunk],
            snap: GraphSnapshot) -> Resolution:
    plan = _Plan()
    res = Resolution(plan=plan.seed, existing=snap.existing_keys())
    std = doc.code
    if std and std not in snap.standards:
        # a standard we have not seeded; a person fills in authority and dates later
        plan.node("Standard", std, {"code": std, "title": _title(doc), "family": std.split()[0],
                                    "status": "unreviewed", "file": doc.file})
        res.created["Standard"] = 1

    # every paragraph becomes a Section with its verbatim text and a SourceChunk
    parts: dict[str, list[Chunk]] = {}
    for c in chunks:
        parts.setdefault(section_id(c.id), []).append(c)
    for sid, cs in parts.items():
        plan.node("Section", sid, {
            "id": sid, "number": cs[0].number or "intro", "heading": cs[0].heading,
            "text": "\n\n".join(c.text for c in cs), "source": doc.file,
            "confidence": _confidence(cs[0], 1.0)})
        if std:
            plan.rel("HAS_SECTION", ("Standard", std), ("Section", sid))
        for c in cs:
            plan.node("SourceChunk", c.id, {"id": c.id, "file": doc.file, "page": c.page,
                                            "text": c.text, "confidence": _confidence(c, 1.0)})
            plan.rel("EXTRACTED_FROM", ("Section", sid), ("SourceChunk", c.id))

    sections = snap.sections | set(parts)
    requirements = {sid: list(reqs) for sid, reqs in snap.requirements.items()}
    definitions = dict(snap.definitions)
    equations = dict(snap.equations)

    for r in results:
        chunk, sid = r.chunk, section_id(r.chunk.id)
        src = ("SourceChunk", chunk.id)
        conf = _confidence(chunk, EXTRACTION_CONFIDENCE)

        for req in r.extraction.requirements:
            known = requirements.setdefault(sid, [])
            best = max(known, key=lambda k: similarity(k[1], req.text), default=None)
            if best and similarity(best[1], req.text) >= MATCH_THRESHOLD:
                rid = best[0]
                res.matched["Requirement"] += 1
            else:
                used = [int(m.group(1)) for k, _ in known if (m := re.search(r"#R(\d+)$", k))]
                rid = f"{sid}#R{max(used, default=0) + 1}"
                known.append((rid, req.text))
                plan.node("Requirement", rid, {"id": rid, "type": req.type,
                                               "obligation": req.obligation, "text": req.text,
                                               "source": doc.file, "confidence": conf})
                res.created["Requirement"] += 1
            plan.rel("HAS_REQUIREMENT", ("Section", sid), ("Requirement", rid))
            plan.rel("EXTRACTED_FROM", ("Requirement", rid), src)
            for code in req.applies_to:
                label = snap.code_labels.get(code)
                if label:
                    plan.rel("APPLIES_TO", ("Requirement", rid), (label, code))

        for d in r.extraction.definitions:
            did = definitions.get(d.term.lower())
            if did:
                res.matched["Definition"] += 1
            else:
                did = f"DEF:{slug(d.term)}"
                definitions[d.term.lower()] = did
                plan.node("Definition", did, {"id": did, "term": d.term.strip(), "text": d.text,
                                              "source": doc.file, "confidence": conf})
                res.created["Definition"] += 1
            plan.rel("DEFINES", ("Section", sid), ("Definition", did))
            plan.rel("EXTRACTED_FROM", ("Definition", did), src)

        for i, eq in enumerate(r.extraction.equations, start=1):
            code = equations.get(norm_expr(eq.expression))
            if code:
                res.matched["Equation"] += 1
            else:
                code = f"EQX-{sid}#{i}"
                equations[norm_expr(eq.expression)] = code
                plan.node("Equation", code, {"code": code, "name": eq.name,
                                             "expression": eq.expression, "kind": "extracted",
                                             "source": doc.file, "confidence": conf})
                for role, item, sign in expression_items(eq.expression):
                    plan.rel("USES", ("Equation", code), ("LineItem", item),
                             {"role": role, "sign": sign})
                plan.rel("DERIVED_FROM", ("Equation", code), ("Section", sid))
                res.created["Equation"] += 1
            plan.rel("EXTRACTED_FROM", ("Equation", code), src)

        for ref in r.references:
            if ref.section and ref.section in sections and ref.section != sid:
                plan.rel("REFERS_TO", ("Section", sid), ("Section", ref.section))
            elif ref.standard and ref.standard != doc.code and ref.standard in snap.standards:
                plan.rel("REFERS_TO", ("Section", sid), ("Standard", ref.standard))

        res.proposals += [{"chunk": chunk.id, **p.model_dump()} for p in r.extraction.proposals]

    res.created["Section"] = len([s for s in parts if s not in snap.sections])
    res.matched["Section"] = len(parts) - res.created["Section"]
    res.created["SourceChunk"] = len(chunks)
    return res
