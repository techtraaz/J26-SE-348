from collections import defaultdict

from app.ontology.model import Ontology


def _edges(onto: Ontology) -> list[tuple[str, str, str]]:
    return [(r.type, a, b) for r in onto.relationships.values()
            for a in r.sources for b in r.targets]


def layer_overview(onto: Ontology) -> str:
    links: dict[tuple[str, str], set[str]] = defaultdict(set)
    for rel, a, b in _edges(onto):
        la, lb = onto.node(a).layer, onto.node(b).layer
        if la != lb:
            links[(la, lb)].add(rel)
    lines = ["flowchart LR"]
    for layer in onto.layers:
        lines.append(f'    {layer}["{layer} ({len(onto.labels_in_layer(layer))} types)"]')
    for (la, lb), rels in sorted(links.items()):
        lines.append(f"    {la} -->|{' / '.join(sorted(rels))}| {lb}")
    return "\n".join(lines)


def layer_diagram(onto: Ontology, layer: str) -> str:
    labels = set(onto.labels_in_layer(layer))
    pairs: dict[tuple[str, str], list[str]] = defaultdict(list)
    for rel, a, b in _edges(onto):
        if a in labels and b in labels:
            pairs[(a, b)].append(rel)
    lines = ["flowchart LR"]
    lines += [f"    {label}" for label in onto.labels_in_layer(layer)]
    for (a, b), rels in sorted(pairs.items()):
        lines.append(f"    {a} -->|{' / '.join(sorted(rels))}| {b}")
    return "\n".join(lines)


def cross_layer_table(onto: Ontology) -> str:
    rows: dict[str, list[str]] = defaultdict(list)
    for rel, a, b in _edges(onto):
        if onto.node(a).layer != onto.node(b).layer:
            rows[rel].append(f"{a} → {b}")
    lines = ["| Relationship | Connects |", "|---|---|"]
    lines += [f"| `{rel}` | {', '.join(pairs)} |" for rel, pairs in sorted(rows.items())]
    return "\n".join(lines)


def markdown(onto: Ontology) -> str:
    parts = ["### Layer overview", "", "```mermaid", layer_overview(onto), "```", ""]
    for layer, description in onto.layers.items():
        parts += [f"### {layer.capitalize()} layer", "", description, ""]
        rows = ["| Node | Key | Description |", "|---|---|---|"]
        rows += [f"| `{label}` | `{onto.node(label).key}` | {onto.node(label).description} |"
                 for label in onto.labels_in_layer(layer)]
        parts += rows + [""]
        parts += ["```mermaid", layer_diagram(onto, layer), "```", ""]
    parts += ["### Links between layers", "", cross_layer_table(onto)]
    return "\n".join(parts)
