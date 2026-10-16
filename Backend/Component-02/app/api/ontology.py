from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from neo4j.exceptions import DriverError, Neo4jError

from app.graph import neo4j_client
from app.ontology import diagram
from app.ontology.model import load_ontology

router = APIRouter(prefix="/ontology", tags=["ontology"])


@router.get("")
def get_ontology() -> dict:
    onto = load_ontology()
    return {
        "name": onto.name,
        "version": onto.version,
        "common_properties": onto.common_properties,
        "layers": {
            layer: {"description": desc, "nodes": onto.labels_in_layer(layer)}
            for layer, desc in onto.layers.items()
        },
        "nodes": {label: n.model_dump(exclude={"label"}) for label, n in onto.nodes.items()},
        "relationships": {
            t: {"from": r.sources, "to": r.targets, "properties": r.properties}
            for t, r in onto.relationships.items()
        },
    }


@router.get("/nodes/{label}")
def get_node_type(label: str) -> dict:
    onto = load_ontology()
    if label not in onto.nodes:
        raise HTTPException(404, f"Unknown node type '{label}'")
    out_rels = sorted(t for t, r in onto.relationships.items() if label in r.sources)
    in_rels = sorted(t for t, r in onto.relationships.items() if label in r.targets)
    return {**onto.node(label).model_dump(), "outgoing": out_rels, "incoming": in_rels}


@router.get("/diagram", response_class=PlainTextResponse)
def get_diagram(layer: str | None = None) -> str:
    onto = load_ontology()
    if layer is None:
        return diagram.layer_overview(onto)
    if layer not in onto.layers:
        raise HTTPException(404, f"Unknown layer '{layer}'")
    return diagram.layer_diagram(onto, layer)


@router.get("/stats")
def get_stats() -> dict:
    try:
        nodes = neo4j_client.run_read(
            "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS count ORDER BY label")
        rels = neo4j_client.run_read(
            "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS count ORDER BY type")
    except (DriverError, Neo4jError) as exc:
        raise HTTPException(503, f"Neo4j unavailable: {exc}") from exc
    return {
        "nodes": {r["label"]: r["count"] for r in nodes},
        "relationships": {r["type"]: r["count"] for r in rels},
        "total_nodes": sum(r["count"] for r in nodes),
        "total_relationships": sum(r["count"] for r in rels),
    }
