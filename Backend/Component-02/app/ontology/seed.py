from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

from app.ontology.model import Ontology

SEED_DIR = Path(__file__).with_name("seed")

_TYPES = {
    "string": (str,),
    "int": (int,),
    "float": (int, float),
    "bool": (bool,),
    "date": (date,),
    "datetime": (datetime,),
    "list": (list,),
    "vector": (list,),
}


@dataclass
class Rel:
    type: str
    source: tuple[str, str]
    target: tuple[str, str]
    props: dict = field(default_factory=dict)


@dataclass
class Seed:
    nodes: dict[str, list[dict]] = field(default_factory=lambda: defaultdict(list))
    rels: list[Rel] = field(default_factory=list)
    files: list[str] = field(default_factory=list)


def parse_ref(ref: str) -> tuple[str, str]:
    label, _, key = ref.partition(":")
    return label.strip(), key.strip()


def load_seed(seed_dir: Path = SEED_DIR) -> Seed:
    seed = Seed()
    for path in sorted(seed_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        seed.files.append(path.name)
        for label, items in (data.get("nodes") or {}).items():
            seed.nodes[label].extend(items)
        for rel_type, rows in (data.get("relationships") or {}).items():
            for row in rows:
                props = row[2] if len(row) > 2 else {}
                seed.rels.append(Rel(rel_type, parse_ref(row[0]), parse_ref(row[1]), props))
    return seed


def _type_ok(value, prop_type: str) -> bool:
    if isinstance(value, bool) and prop_type != "bool":
        return False
    if prop_type == "date" and isinstance(value, datetime):
        return False
    return isinstance(value, _TYPES[prop_type])


def _check_props(owner: str, props: dict, allowed: dict[str, str]) -> list[str]:
    errors = []
    for name, value in props.items():
        if name not in allowed:
            errors.append(f"{owner}: unknown property '{name}'")
        elif value is not None and not _type_ok(value, allowed[name]):
            errors.append(f"{owner}: '{name}' should be {allowed[name]}, got {value!r}")
    return errors


# existing: keys already in the graph, so relationships may point at them
def validate(seed: Seed, onto: Ontology, existing: dict[str, set] | None = None) -> list[str]:
    errors: list[str] = []
    keys: dict[str, set] = defaultdict(set)
    known = existing or {}
    for label, items in seed.nodes.items():
        if label not in onto.nodes:
            errors.append(f"unknown node label '{label}'")
            continue
        node = onto.node(label)
        for item in items:
            key = item.get(node.key)
            owner = f"{label}:{key}"
            if key is None:
                errors.append(f"{label}: item without key '{node.key}': {item}")
                continue
            if key in keys[label]:
                errors.append(f"{owner}: duplicate")
            keys[label].add(key)
            missing = [r for r in node.required if item.get(r) is None]
            if missing:
                errors.append(f"{owner}: missing required {missing}")
            errors += _check_props(owner, item, {**onto.common_properties, **node.properties})

    for rel in seed.rels:
        owner = f"{rel.type} {rel.source} -> {rel.target}"
        if rel.type not in onto.relationships:
            errors.append(f"{owner}: unknown relationship type")
            continue
        if not onto.has_relationship(rel.type, rel.source[0], rel.target[0]):
            errors.append(f"{owner}: not allowed by ontology")
            continue
        for label, key in (rel.source, rel.target):
            if key not in keys.get(label, set()) and key not in known.get(label, set()):
                errors.append(f"{owner}: {label}:{key} not in seed")
        errors += _check_props(owner, rel.props, onto.relationships[rel.type].properties)
    return errors


BATCH = 500


def _batches(rows: list, size: int = BATCH):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


# item values win over the defaults, so an item can carry its own source or confidence
def write(seed: Seed, onto: Ontology, run, source: str = "seed",
          confidence: float = 1.0) -> dict[str, int]:
    counts: dict[str, int] = {}
    meta = {"source": source, "confidence": confidence, "version": onto.version}
    for label, items in seed.nodes.items():
        key = onto.node(label).key
        rows = [{"key": i[key], "props": {k: v for k, v in i.items() if v is not None}}
                for i in items]
        for batch in _batches(rows):
            run(
                f"UNWIND $rows AS row MERGE (n:{label} {{{key}: row.key}}) "
                "SET n.source = $source, n.confidence = $confidence, "
                "n.ontology_version = $version, n.created_at = coalesce(n.created_at, datetime()) "
                "SET n += row.props",
                rows=batch,
                **meta,
            )
        counts[label] = len(items)

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for rel in seed.rels:
        groups[(rel.type, rel.source[0], rel.target[0])].append(
            {"a": rel.source[1], "b": rel.target[1], "props": rel.props})
    for (rel_type, la, lb), rows in groups.items():
        ka, kb = onto.node(la).key, onto.node(lb).key
        for batch in _batches(rows):
            run(
                f"UNWIND $rows AS row MATCH (a:{la} {{{ka}: row.a}}) "
                f"MATCH (b:{lb} {{{kb}: row.b}}) MERGE (a)-[r:{rel_type}]->(b) SET r += row.props",
                rows=batch,
            )
        counts[rel_type] = counts.get(rel_type, 0) + len(rows)
    return counts
