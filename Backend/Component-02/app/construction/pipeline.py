import re
from dataclasses import asdict, dataclass, field
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.construction.chunker import chunk_document
from app.construction.classify import classify_document
from app.construction.context import GraphReader, base_context
from app.construction.documents import Chunk, LoadedDocument
from app.construction.llm import LLM, LLMError
from app.construction.prompts import SYSTEM, build_user_prompt
from app.construction.schema import ChunkExtraction, ExtractionContext
from app.construction.validate import ValidatedChunk, validate_chunk

KG_KINDS = {"standard", "amendment", "legislation"}
MIN_CHARS = 40
_DELETED = re.compile(r"^\S+\s+\[deleted\]\s*$", re.IGNORECASE)


class IngestState(TypedDict, total=False):
    doc: LoadedDocument
    kind: str
    chunks: list[Chunk]
    context: ExtractionContext
    known: dict[str, list[str]]
    extractions: dict[str, ChunkExtraction]
    results: list[ValidatedChunk]
    skipped: list[str]
    errors: dict[str, str]


@dataclass
class IngestResult:
    file: str
    code: str | None
    kind: str
    chunks: int
    results: list[ValidatedChunk] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "file": self.file, "code": self.code, "kind": self.kind, "chunks": self.chunks,
            "skipped": self.skipped, "errors": self.errors,
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
    """chunk -> classify -> retrieve context -> extract (LLM) -> validate."""

    def __init__(self, llm: LLM, reader: GraphReader, max_chunks: int | None = None):
        self.llm = llm
        self.reader = reader
        self.max_chunks = max_chunks
        self.graph = self._build()

    def _build(self):
        g = StateGraph(IngestState)
        g.add_node("chunk", self.chunk)
        g.add_node("classify", self.classify)
        g.add_node("retrieve_context", self.retrieve_context)
        g.add_node("extract", self.extract)
        g.add_node("validate", self.validate)
        g.add_edge(START, "chunk")
        g.add_edge("chunk", "classify")
        g.add_conditional_edges("classify", lambda s: "kg" if s["kind"] in KG_KINDS else "skip",
                                {"kg": "retrieve_context", "skip": END})
        g.add_edge("retrieve_context", "extract")
        g.add_edge("extract", "validate")
        g.add_edge("validate", END)
        return g.compile()

    def chunk(self, state: IngestState) -> dict:
        return {"chunks": chunk_document(state["doc"])}

    def classify(self, state: IngestState) -> dict:
        return {"kind": classify_document(state["doc"])}

    def retrieve_context(self, state: IngestState) -> dict:
        code = state["doc"].code
        known = self.reader.known_for_standard(code) if code else {}
        return {"context": base_context(self.reader), "known": known}

    def extract(self, state: IngestState) -> dict:
        doc, base = state["doc"], state["context"]
        todo = [c for c in state["chunks"] if _worth_extracting(c)]
        skipped = [c.id for c in state["chunks"] if not _worth_extracting(c)]
        if self.max_chunks is not None:
            skipped += [c.id for c in todo[self.max_chunks:]]
            todo = todo[:self.max_chunks]
        extractions, errors = {}, {}
        for chunk in todo:
            ctx = ExtractionContext(base.line_items, base.account_classes, base.document_types,
                                    state["known"].get(chunk.id, []))
            try:
                extractions[chunk.id] = self.llm.extract(
                    SYSTEM, build_user_prompt(chunk, doc.code, ctx), ChunkExtraction)
            except LLMError as exc:
                errors[chunk.id] = str(exc)
        return {"extractions": extractions, "errors": errors, "skipped": skipped}

    def validate(self, state: IngestState) -> dict:
        by_id = {c.id: c for c in state["chunks"]}
        standards = set(self.reader.codes("Standard"))
        return {"results": [
            validate_chunk(by_id[cid], ext, state["context"], standards)
            for cid, ext in state["extractions"].items()
        ]}

    def run(self, doc: LoadedDocument) -> IngestResult:
        out = self.graph.invoke({"doc": doc})
        return IngestResult(
            file=doc.file, code=doc.code, kind=out["kind"], chunks=len(out["chunks"]),
            results=out.get("results", []), skipped=out.get("skipped", []),
            errors=out.get("errors", {}))

    def mermaid(self) -> str:
        return self.graph.get_graph().draw_mermaid()
