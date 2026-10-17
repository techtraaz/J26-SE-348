import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.construction.chunker import chunk_document
from app.construction.classify import classify_document
from app.construction.context import GraphReader, GraphSnapshot, base_context
from app.construction.documents import Chunk, LoadedDocument
from app.construction.llm import LLM, LLMError
from app.construction.prompts import SYSTEM, build_user_prompt
from app.construction.resolve import Resolution, resolve
from app.construction.schema import ChunkExtraction, ExtractionContext
from app.construction.validate import ValidatedChunk, validate_chunk
from app.ontology.model import load_ontology
from app.ontology.seed import validate as validate_plan
from app.ontology.seed import write as write_plan

KG_KINDS = {"standard", "amendment", "legislation"}
MIN_CHARS = 40
EMBED_BATCH = 32
_DELETED = re.compile(r"^\S+\s+\[deleted\]\s*$", re.IGNORECASE)


class IngestState(TypedDict, total=False):
    doc: LoadedDocument
    kind: str
    chunks: list[Chunk]
    context: ExtractionContext
    snapshot: GraphSnapshot
    extractions: dict[str, ChunkExtraction]
    results: list[ValidatedChunk]
    resolution: Resolution
    skipped: list[str]
    errors: dict[str, str]
    plan_errors: list[str]
    written: dict[str, int]


@dataclass
class IngestResult:
    file: str
    code: str | None
    kind: str
    chunks: int
    results: list[ValidatedChunk] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    matched: Counter = field(default_factory=Counter)
    created: Counter = field(default_factory=Counter)
    proposals: list[dict] = field(default_factory=list)
    plan_errors: list[str] = field(default_factory=list)
    written: dict[str, int] = field(default_factory=dict)

    def summary(self) -> dict:
        ext = [r.extraction for r in self.results]
        return {
            "file": self.file, "code": self.code, "kind": self.kind, "chunks": self.chunks,
            "sent_to_llm": len(self.results) + len(self.errors), "skipped": len(self.skipped),
            "llm_errors": len(self.errors),
            "requirements": sum(len(e.requirements) for e in ext),
            "definitions": sum(len(e.definitions) for e in ext),
            "equations": sum(len(e.equations) for e in ext),
            "issues": dict(Counter(i.action for r in self.results for i in r.issues)),
            "created": dict(self.created), "matched": dict(self.matched),
            "proposals": len(self.proposals), "plan_errors": self.plan_errors,
            "written": sum(self.written.values()),
        }

    def to_dict(self) -> dict:
        return {
            "file": self.file, "code": self.code, "kind": self.kind, "chunks": self.chunks,
            "skipped": self.skipped, "errors": self.errors, "matched": dict(self.matched),
            "created": dict(self.created), "proposals": self.proposals,
            "plan_errors": self.plan_errors, "written": self.written,
            "results": [{
                "chunk": asdict(r.chunk),
                "extraction": r.extraction.model_dump(),
                "references": [asdict(x) for x in r.references],
                "issues": [asdict(i) for i in r.issues],
            } for r in self.results],
        }


def _worth_extracting(chunk: Chunk) -> bool:
    return chunk.number is not None and len(chunk.text) >= MIN_CHARS \
        and not _DELETED.match(chunk.text.strip())


class KGPipeline:
    """chunk -> classify -> retrieve context -> extract (LLM) -> validate -> resolve -> write.
    Without run_write nothing is written (dry run)."""

    def __init__(self, llm: LLM, reader: GraphReader, run_write=None,
                 max_chunks: int | None = None, embed: bool = True):
        self.llm = llm
        self.reader = reader
        self.run_write = run_write
        self.embed = embed
        self.max_chunks = max_chunks
        self.onto = load_ontology()
        self.graph = self._build()

    def _build(self):
        g = StateGraph(IngestState)
        for name in ("chunk", "classify", "retrieve_context", "extract", "validate",
                     "resolve", "write"):
            g.add_node(name, getattr(self, name))
        g.add_edge(START, "chunk")
        g.add_edge("chunk", "classify")
        g.add_conditional_edges("classify", lambda s: "kg" if s["kind"] in KG_KINDS else "skip",
                                {"kg": "retrieve_context", "skip": END})
        g.add_edge("retrieve_context", "extract")
        g.add_edge("extract", "validate")
        g.add_edge("validate", "resolve")
        g.add_edge("resolve", "write")
        g.add_edge("write", END)
        return g.compile()

    def chunk(self, state: IngestState) -> dict:
        return {"chunks": chunk_document(state["doc"])}

    def classify(self, state: IngestState) -> dict:
        return {"kind": classify_document(state["doc"])}

    def retrieve_context(self, state: IngestState) -> dict:
        return {"context": base_context(self.reader),
                "snapshot": self.reader.snapshot(state["doc"].code)}

    def extract(self, state: IngestState) -> dict:
        doc, base, snap = state["doc"], state["context"], state["snapshot"]
        todo = [c for c in state["chunks"] if _worth_extracting(c)]
        skipped = [c.id for c in state["chunks"] if not _worth_extracting(c)]
        if self.max_chunks is not None:
            skipped += [c.id for c in todo[self.max_chunks:]]
            todo = todo[:self.max_chunks]
        extractions, errors = {}, {}
        for chunk in todo:
            ctx = ExtractionContext(base.line_items, base.account_classes, base.document_types,
                                    snap.known(chunk.id))
            try:
                extractions[chunk.id] = self.llm.extract(
                    SYSTEM, build_user_prompt(chunk, doc.code, ctx), ChunkExtraction)
            except LLMError as exc:
                errors[chunk.id] = str(exc)
        return {"extractions": extractions, "errors": errors, "skipped": skipped}

    def validate(self, state: IngestState) -> dict:
        by_id = {c.id: c for c in state["chunks"]}
        standards = state["snapshot"].standards
        return {"results": [
            validate_chunk(by_id[cid], ext, state["context"], standards)
            for cid, ext in state["extractions"].items()
        ]}

    def resolve(self, state: IngestState) -> dict:
        return {"resolution": resolve(state["doc"], state["chunks"], state["results"],
                                      state["snapshot"])}

    def write(self, state: IngestState) -> dict:
        res = state["resolution"]
        errors = validate_plan(res.plan, self.onto, res.existing)
        if errors or self.run_write is None:
            return {"plan_errors": errors, "written": {}}
        chunks = res.plan.nodes.get("SourceChunk", []) if self.embed else []
        try:
            for i in range(0, len(chunks), EMBED_BATCH):
                batch = chunks[i:i + EMBED_BATCH]
                for item, vector in zip(batch, self.llm.embed([c["text"] for c in batch]),
                                        strict=True):
                    item["embedding"] = vector
        except LLMError as exc:
            errors = [f"embeddings skipped: {exc}"]
        written = write_plan(res.plan, self.onto, self.run_write, source=state["doc"].file,
                             confidence=1.0)
        return {"plan_errors": errors, "written": written}

    def run(self, doc: LoadedDocument) -> IngestResult:
        out = self.graph.invoke({"doc": doc})
        res = out.get("resolution")
        return IngestResult(
            file=doc.file, code=doc.code, kind=out["kind"], chunks=len(out["chunks"]),
            results=out.get("results", []), skipped=out.get("skipped", []),
            errors=out.get("errors", {}),
            matched=res.matched if res else Counter(), created=res.created if res else Counter(),
            proposals=res.proposals if res else [], plan_errors=out.get("plan_errors", []),
            written=out.get("written", {}))

    def mermaid(self) -> str:
        return self.graph.get_graph().draw_mermaid()
