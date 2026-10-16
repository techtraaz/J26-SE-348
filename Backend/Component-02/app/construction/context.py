from functools import cache
from typing import Protocol

from app.construction.schema import ExtractionContext
from app.ontology.model import load_ontology
from app.ontology.seed import load_seed


class GraphReader(Protocol):
    def codes(self, label: str) -> list[str]: ...

    def known_for_standard(self, code: str) -> dict[str, list[str]]: ...


def base_context(reader: GraphReader) -> ExtractionContext:
    return ExtractionContext(
        line_items=reader.codes("LineItem"),
        account_classes=reader.codes("AccountClass"),
        document_types=reader.codes("DocumentType"),
    )


class Neo4jReader:
    def __init__(self, run_read):
        self.run_read = run_read
        self.onto = load_ontology()
        self.codes = cache(self._codes)

    def _codes(self, label: str) -> list[str]:
        key = self.onto.node(label).key  # label checked against the ontology before use in Cypher
        rows = self.run_read(f"MATCH (n:{label}) RETURN n.{key} AS code ORDER BY code")
        return [r["code"] for r in rows]

    # one query per standard, the AuraDB round trip is the slow part
    def known_for_standard(self, code: str) -> dict[str, list[str]]:
        rows = self.run_read(
            "MATCH (:Standard {code: $code})-[:HAS_SECTION]->(s:Section) "
            "OPTIONAL MATCH (s)-[:HAS_REQUIREMENT]->(r:Requirement) "
            "OPTIONAL MATCH (s)-[:DEFINES]->(d:Definition) "
            "RETURN s.id AS id, collect(DISTINCT r.id + ': ' + r.text) AS reqs, "
            "collect(DISTINCT 'definition ' + d.term) AS defs",
            code=code,
        )
        return {r["id"]: r["reqs"] + r["defs"] for r in rows}


class SeedReader:
    """Same answers from the seed YAML, for tests and offline runs."""

    def __init__(self, seed=None):
        self.seed = seed or load_seed()
        self.onto = load_ontology()

    def codes(self, label: str) -> list[str]:
        key = self.onto.node(label).key
        return sorted(item[key] for item in self.seed.nodes.get(label, []))

    def known_for_standard(self, code: str) -> dict[str, list[str]]:
        reqs = {r["id"]: r["text"] for r in self.seed.nodes.get("Requirement", [])}
        terms = {d["id"]: d["term"] for d in self.seed.nodes.get("Definition", [])}
        sections = {r.target[1] for r in self.seed.rels
                    if r.type == "HAS_SECTION" and r.source == ("Standard", code)}
        out: dict[str, list[str]] = {}
        for rel in self.seed.rels:
            sid = rel.source[1]
            if rel.source[0] != "Section" or sid not in sections:
                continue
            if rel.type == "HAS_REQUIREMENT":
                out.setdefault(sid, []).append(f"{rel.target[1]}: {reqs[rel.target[1]]}")
            elif rel.type == "DEFINES":
                out.setdefault(sid, []).append(f"definition {terms[rel.target[1]]}")
        return out
