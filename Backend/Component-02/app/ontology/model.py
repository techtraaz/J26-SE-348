from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

SCHEMA_PATH = Path(__file__).with_name("schema.yaml")
PROPERTY_TYPES = {"string", "int", "float", "bool", "date", "datetime"}


class NodeType(BaseModel):
    label: str
    layer: str
    key: str
    description: str
    properties: dict[str, str]
    required: list[str] = []


class RelationshipType(BaseModel):
    type: str
    sources: list[str] = Field(alias="from")
    targets: list[str] = Field(alias="to")
    properties: dict[str, str] = {}


class Ontology(BaseModel):
    version: int
    name: str
    common_properties: dict[str, str]
    layers: dict[str, str]
    nodes: dict[str, NodeType]
    relationships: dict[str, RelationshipType]

    @model_validator(mode="after")
    def check_consistency(self) -> "Ontology":
        for label, node in self.nodes.items():
            if node.layer not in self.layers:
                raise ValueError(f"{label}: unknown layer '{node.layer}'")
            if node.key not in node.properties:
                raise ValueError(f"{label}: key '{node.key}' is not a property")
            missing = set(node.required) - set(node.properties)
            if missing:
                raise ValueError(f"{label}: required but not defined {sorted(missing)}")
            _check_types(label, node.properties)
        for rel_type, rel in self.relationships.items():
            for label in rel.sources + rel.targets:
                if label not in self.nodes:
                    raise ValueError(f"{rel_type}: unknown node label '{label}'")
            _check_types(rel_type, rel.properties)
        _check_types("common_properties", self.common_properties)
        return self

    def node(self, label: str) -> NodeType:
        return self.nodes[label]

    def has_relationship(self, rel_type: str, source: str, target: str) -> bool:
        rel = self.relationships.get(rel_type)
        return rel is not None and source in rel.sources and target in rel.targets

    def labels_in_layer(self, layer: str) -> list[str]:
        return [label for label, node in self.nodes.items() if node.layer == layer]


def _check_types(owner: str, props: dict[str, str]) -> None:
    bad = {name: t for name, t in props.items() if t not in PROPERTY_TYPES}
    if bad:
        raise ValueError(f"{owner}: unsupported property types {bad}")


def parse_ontology(raw: dict) -> Ontology:
    raw = dict(raw)
    raw["nodes"] = {label: {"label": label, **n} for label, n in raw["nodes"].items()}
    raw["relationships"] = {t: {"type": t, **r} for t, r in raw["relationships"].items()}
    return Ontology.model_validate(raw)


@lru_cache
def load_ontology(path: Path = SCHEMA_PATH) -> Ontology:
    return parse_ontology(yaml.safe_load(path.read_text(encoding="utf-8")))
