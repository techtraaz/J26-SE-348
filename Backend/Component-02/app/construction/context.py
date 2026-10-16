from dataclasses import dataclass, field
from functools import cache
from typing import Protocol

from app.construction.schema import ExtractionContext
from app.ontology.model import load_ontology
from app.ontology.seed import load_seed

CODE_LABELS = ("LineItem", "AccountClass", "DocumentType")


def norm_expr(expression: str) -> str:
    return "".join(expression.split())


@dataclass
class GraphSnapshot:
    """What the graph already holds, used for matching new extractions."""
    standards: set[str] = field(default_factory=set)
    sections: set[str] = field(default_factory=set)
    requirements: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # section -> [(id, text)]
    section_terms: dict[str, list[str]] = field(default_factory=dict)  # section -> terms it defines
    definitions: dict[str, str] = field(default_factory=dict)  # lower term -> id
    equations: dict[str, str] = field(default_factory=dict)  # normalised expression -> code
    code_labels: dict[str, str] = field(default_factory=dict)  # line item / class / doc type -> label

    def known(self, section_id: str) -> list[str]:
        return ([f"{rid}: {text}" for rid, text in self.requirements.get(section_id, [])]
                + [f"definition {t}" for t in self.section_terms.get(section_id, [])])

    def existing_keys(self) -> dict[str, set]:
        keys: dict[str, set] = {"Standard": set(self.standards), "Section": set(self.sections),
                                "Requirement": {rid for reqs in self.requirements.values()
                                                for rid, _ in reqs},
                                "Definition": set(self.definitions.values()),
                                "Equation": set(self.equations.values())}
        for code, label in self.code_labels.items():
            keys.setdefault(label, set()).add(code)
        return keys


class GraphReader(Protocol):
    def codes(self, label: str) -> list[str]: ...

    def snapshot(self, code: str | None) -> GraphSnapshot: ...


def base_context(reader: GraphReader) -> ExtractionContext:
    return ExtractionContext(
        line_items=reader.codes("LineItem"),
        account_classes=reader.codes("AccountClass"),
        document_types=reader.codes("DocumentType"),
    )


def _code_labels(reader: GraphReader) -> dict[str, str]:
    return {code: label for label in CODE_LABELS for code in reader.codes(label)}


class Neo4jReader:
    def __init__(self, run_read):
        self.run_read = run_read
        self.onto = load_ontology()
        self.codes = cache(self._codes)

    def _codes(self, label: str) -> list[str]:
        key = self.onto.node(label).key  # label checked against the ontology before use in Cypher
        rows = self.run_read(f"MATCH (n:{label}) RETURN n.{key} AS code ORDER BY code")
        return [r["code"] for r in rows]

    # a handful of queries per document, the AuraDB round trip is the slow part
    def snapshot(self, code: str | None) -> GraphSnapshot:
        snap = GraphSnapshot(standards=set(self.codes("Standard")), code_labels=_code_labels(self))
        snap.sections = {r["id"] for r in self.run_read("MATCH (s:Section) RETURN s.id AS id")}
        snap.definitions = {r["term"].lower(): r["id"] for r in self.run_read(
            "MATCH (d:Definition) RETURN d.term AS term, d.id AS id")}
        snap.equations = {norm_expr(r["expr"]): r["code"] for r in self.run_read(
            "MATCH (e:Equation) RETURN e.expression AS expr, e.code AS code")}
        if code:
            for r in self.run_read(
                "MATCH (:Standard {code: $code})-[:HAS_SECTION]->(s:Section) "
                "OPTIONAL MATCH (s)-[:HAS_REQUIREMENT]->(r:Requirement) "
                "OPTIONAL MATCH (s)-[:DEFINES]->(d:Definition) "
                "RETURN s.id AS id, collect(DISTINCT [r.id, r.text]) AS reqs, "
                "collect(DISTINCT d.term) AS terms", code=code,
            ):
                snap.requirements[r["id"]] = [tuple(x) for x in r["reqs"] if x[0]]
                snap.section_terms[r["id"]] = r["terms"]
        return snap


class SeedReader:
    """Same answers from the seed YAML, for tests and offline runs."""

    def __init__(self, seed=None):
        self.seed = seed or load_seed()
        self.onto = load_ontology()

    def codes(self, label: str) -> list[str]:
        key = self.onto.node(label).key
        return sorted(item[key] for item in self.seed.nodes.get(label, []))

    def snapshot(self, code: str | None) -> GraphSnapshot:
        nodes = self.seed.nodes
        reqs = {r["id"]: r["text"] for r in nodes.get("Requirement", [])}
        terms = {d["id"]: d["term"] for d in nodes.get("Definition", [])}
        snap = GraphSnapshot(
            standards=set(self.codes("Standard")), sections=set(self.codes("Section")),
            definitions={t.lower(): i for i, t in terms.items()},
            equations={norm_expr(e["expression"]): e["code"] for e in nodes.get("Equation", [])},
            code_labels=_code_labels(self))
        own = {r.target[1] for r in self.seed.rels
               if r.type == "HAS_SECTION" and r.source == ("Standard", code)}
        for rel in self.seed.rels:
            sid = rel.source[1]
            if rel.source[0] != "Section" or sid not in own:
                continue
            if rel.type == "HAS_REQUIREMENT":
                snap.requirements.setdefault(sid, []).append((rel.target[1], reqs[rel.target[1]]))
            elif rel.type == "DEFINES":
                snap.section_terms.setdefault(sid, []).append(terms[rel.target[1]])
        return snap
