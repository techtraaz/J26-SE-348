import re

import openai

from app.config import get_settings
from app.construction.llm import LLMError, get_llm
from app.construction.validate import parse_reference
from app.graph.neo4j_client import run_read

RRF_K = 60
PREVIEW = 400
_LUCENE_SPECIAL = re.compile(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)')

# every hit is returned as the paragraph it belongs to, ready to cite
_SECTION_FIELDS = (
    "sec.id AS section, sec.number AS paragraph, sec.heading AS heading, "
    f"left(sec.text, {PREVIEW}) AS text, st.code AS standard, st.title AS title, "
    "st.status AS status, min(c.page) AS page, min(c.file) AS file")


def escape_lucene(text: str) -> str:
    return _LUCENE_SPECIAL.sub(r"\\\1", text)


def _filter(standard: str | None) -> str:
    return "WHERE $standard IS NULL OR st.code = $standard "


def exact_reference(q: str, run=run_read) -> list[dict]:
    """'LKAS 2:9', 'LKAS 2.9' or 'paragraph 9 of LKAS 2' go straight to that paragraph."""
    standards = {r["code"] for r in run("MATCH (s:Standard) RETURN s.code AS code")}
    ref = parse_reference(q.replace(":", "."), standards)
    if not ref.section:
        return []
    rows = run(
        "MATCH (st:Standard)-[:HAS_SECTION]->(sec:Section {id: $id}) "
        "OPTIONAL MATCH (sec)-[:EXTRACTED_FROM]->(c:SourceChunk) "
        f"RETURN 'Section' AS matched, sec.id AS matched_id, {_SECTION_FIELDS}",
        id=ref.section)
    return [{**r, "score": 1.0, "via": "reference"} for r in rows]


def keyword_search(q: str, limit: int = 10, standard: str | None = None,
                   run=run_read) -> list[dict]:
    rows = run(
        "CYPHER 5 CALL db.index.fulltext.queryNodes('regulatory_text', $q, {limit: $k}) "
        "YIELD node, score "
        "WITH node, score, CASE WHEN node:Section THEN node "
        "ELSE head([(s:Section)-[:HAS_REQUIREMENT|DEFINES]->(node) | s]) END AS sec "
        "OPTIONAL MATCH (st:Standard)-[:HAS_SECTION]->(sec) "
        "OPTIONAL MATCH (sec)-[:EXTRACTED_FROM]->(c:SourceChunk) "
        "WITH node, score, sec, st, c "
        + _filter(standard) +
        "WITH node, score, sec, st, c WHERE sec IS NOT NULL "
        f"RETURN labels(node)[0] AS matched, coalesce(node.id, node.code) AS matched_id, "
        f"max(score) AS score, {_SECTION_FIELDS} "
        "ORDER BY score DESC LIMIT $limit",
        q=escape_lucene(q), k=limit * 3, limit=limit * 3, standard=standard)
    # a paragraph and its requirement can both match; keep one hit per paragraph
    best: dict[str, dict] = {}
    for r in rows:
        hit = best.setdefault(r["section"], {**r, "via": "keyword", "matched": [], "matched_id": []})
        hit["matched"].append(r["matched"])
        hit["matched_id"].append(r["matched_id"])
        hit["score"] = max(hit["score"], r["score"])
    return sorted(best.values(), key=lambda h: h["score"], reverse=True)[:limit]


def semantic_available() -> bool:
    return get_settings().llm_provider != "fake"


def semantic_search(q: str, limit: int = 10, standard: str | None = None,
                    run=run_read, embed=None) -> list[dict]:
    """Nearest chunks by embedding. Needs real embeddings in the graph."""
    embed = embed or get_llm().embed
    vector = embed([q])[0]
    rows = run(
        "CYPHER 5 CALL db.index.vector.queryNodes('source_chunk_embedding', $k, $vector) "
        "YIELD node AS hit, score "
        "MATCH (sec:Section)-[:EXTRACTED_FROM]->(hit) "
        "OPTIONAL MATCH (st:Standard)-[:HAS_SECTION]->(sec) "
        "OPTIONAL MATCH (sec)-[:EXTRACTED_FROM]->(c:SourceChunk) "
        "WITH hit, score, sec, st, c "
        + _filter(standard) +
        f"RETURN 'SourceChunk' AS matched, hit.id AS matched_id, max(score) AS score, "
        f"{_SECTION_FIELDS} ORDER BY score DESC LIMIT $limit",
        k=limit * 3, vector=vector, limit=limit, standard=standard)
    return [{**r, "via": "semantic"} for r in rows]


def fuse(*ranked: list[dict], limit: int = 10) -> list[dict]:
    """Reciprocal rank fusion: a paragraph found by both searches rises to the top."""
    scores: dict[str, float] = {}
    best: dict[str, dict] = {}
    for results in ranked:
        for rank, hit in enumerate(results, start=1):
            key = hit["section"]
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
            if key in best:
                best[key]["via"] = "+".join(sorted({*best[key]["via"].split("+"), hit["via"]}))
            else:
                best[key] = dict(hit)
    order = sorted(scores, key=scores.get, reverse=True)[:limit]
    return [{**best[k], "score": round(scores[k], 5)} for k in order]


def search(q: str, mode: str = "hybrid", limit: int = 10, standard: str | None = None,
           run=run_read, embed=None) -> dict:
    exact = exact_reference(q, run)
    keyword = keyword_search(q, limit, standard, run) if mode in ("keyword", "hybrid") else []
    semantic, note = [], None
    if mode in ("semantic", "hybrid"):
        if embed is None and not semantic_available():
            note = "semantic search needs a real embedding model (LLM_PROVIDER=fake)"
        else:
            try:
                semantic = semantic_search(q, limit, standard, run, embed)
            except (LLMError, openai.OpenAIError) as exc:
                note = f"semantic search unavailable: {exc}"
    results = fuse(exact, keyword, semantic, limit=limit) if exact or (keyword and semantic) \
        else (keyword or semantic)[:limit]
    return {"query": q, "mode": mode, "results": results, "note": note}
