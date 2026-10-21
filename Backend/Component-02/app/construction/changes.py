from app.construction.resolve import Resolution
from app.ontology.model import Ontology

# SourceChunks repeat the Section text, so they are counted but not listed or drawn
LISTED = ("Standard", "Section", "Requirement", "Definition", "Equation")
MAX_NODES = 600
MAX_LINKS = 1200
CAPTION_CHARS = 240


def _cut(text: str | None, limit: int = CAPTION_CHARS) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def caption(label: str, props: dict) -> str:
    if label == "Standard":
        return _cut(f"{props.get('code')} {props.get('title') or ''}")
    if label == "Section":
        return _cut(props.get("heading") or props.get("text"), 120)
    if label == "Definition":
        return _cut(f"{props.get('term')}: {props.get('text') or ''}")
    if label == "Equation":
        return _cut(f"{props.get('name') or ''} {props.get('expression')}")
    return _cut(props.get("text"))


def describe(res: Resolution, onto: Ontology) -> dict:
    """What a run adds to the graph: new nodes per type, and the touched part of the
    graph (new and already known nodes) for drawing."""
    new: dict[str, list[dict]] = {}
    nodes: dict[str, dict] = {}
    for label in LISTED:
        key = onto.node(label).key
        known = res.existing.get(label, set())
        for props in res.plan.nodes.get(label, []):
            item = {"id": f"{label}:{props[key]}", "label": label, "key": props[key],
                    "caption": caption(label, props), "new": props[key] not in known}
            nodes[item["id"]] = item
            if item["new"]:
                new.setdefault(label, []).append(
                    {"key": props[key], "caption": item["caption"],
                     "section": props.get("id", "").split("#")[0] if label == "Requirement"
                     else None})

    links = []
    for rel in res.plan.rels:
        if "SourceChunk" in (rel.source[0], rel.target[0]):
            continue
        ends = []
        for label, key in (rel.source, rel.target):
            nid = f"{label}:{key}"
            nodes.setdefault(nid, {"id": nid, "label": label, "key": key, "caption": key,
                                   "new": False})
            ends.append(nid)
        links.append({"source": ends[0], "target": ends[1], "type": rel.type})

    truncated = len(nodes) > MAX_NODES or len(links) > MAX_LINKS
    kept = dict(list(nodes.items())[:MAX_NODES])
    links = [lk for lk in links if lk["source"] in kept and lk["target"] in kept][:MAX_LINKS]
    return {"new": new, "graph": {"nodes": list(kept.values()), "links": links,
                                  "truncated": truncated}}
