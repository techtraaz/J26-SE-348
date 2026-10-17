# Fixed queries behind Component 03's KGClient, same shapes as its mock_data.json
import re

from app.graph.neo4j_client import run_read

_FUNCS = {"min", "max", "abs", "not", "and", "or", "required", "fields", "present",
          "confidence", "prior", "child", "parent"}
_IDENT = re.compile(r"\b[a-z_][a-z0-9_]*\b")


def field_map(run=run_read) -> dict[str, str]:
    """Every name a document field may use (code or alias) -> line item code."""
    out = {}
    for r in run("MATCH (li:LineItem) RETURN li.code AS code, coalesce(li.aliases, []) AS aliases"):
        out[r["code"]] = r["code"]
        for alias in r["aliases"]:
            out[alias] = r["code"]
    return out


def _variables(expression: str, fields: dict[str, str], aliases: dict[str, list[str]]) -> list[dict]:
    names = []
    for name in _IDENT.findall(expression):
        if name in fields and name not in _FUNCS and name not in names:
            names.append(name)
    return [{"name": n, "line_item": fields[n], "aliases": aliases.get(fields[n], [])}
            for n in names]


def get_rules(doc_type: str, run=run_read) -> list[dict]:
    """Policy rules with limits, e.g. POL-07 dual approval above 100,000."""
    return run(
        "MATCH (p:PolicyRule)-[:CHECKS_DOC_TYPE]->(:DocumentType {code: $doc_type}) "
        "RETURN p.rule_id AS rule_id, p.text AS text, p.limit AS limit ORDER BY rule_id",
        doc_type=doc_type)


def get_check_rules(doc_type: str, run=run_read) -> list[dict]:
    """Check rules for a document type. `variables` maps each name in the expression to its
    line item and the other names a document may use for the same amount."""
    rows = run(
        "MATCH (r:CheckRule)-[:CHECKS_DOC_TYPE]->(:DocumentType {code: $doc_type}) "
        "RETURN r.rule_id AS rule_id, r.name AS name, r.expression AS expression, "
        "r.severity AS severity ORDER BY rule_id",
        doc_type=doc_type)
    if not rows:
        return []
    items = run("MATCH (li:LineItem) RETURN li.code AS code, coalesce(li.aliases, []) AS aliases")
    aliases = {r["code"]: r["aliases"] for r in items}
    fields = {name: r["code"] for r in items for name in [r["code"], *r["aliases"]]}
    return [{**r, "variables": _variables(r["expression"], fields, aliases)} for r in rows]


def get_evidence_chain(doc_id: str, run=run_read) -> list[str]:
    """The document plus every document it supports or is supported by (CHILD_OF, any depth)."""
    rows = run(
        "MATCH (d:SourceDocument {doc_id: $doc_id}) "
        "OPTIONAL MATCH (d)-[:CHILD_OF*1..10]-(other:SourceDocument) "
        "RETURN collect(DISTINCT other.doc_id) AS others",
        doc_id=doc_id)
    others = rows[0]["others"] if rows else []
    return [doc_id, *sorted(o for o in others if o != doc_id)]


def get_postings(case_id: str, run=run_read) -> list[dict]:
    """Ledger postings of an engagement. Filled by the evidence ledger (Phase 5)."""
    return run(
        "MATCH (:Engagement {case_id: $case_id})<-[:IN_ENGAGEMENT]-(d:SourceDocument)"
        "<-[:RECORDS]-(e:LedgerEntry) "
        "RETURN e.entry_id AS entry_id, d.doc_id AS doc_id, d.doc_type AS doc_type, "
        "e.action AS action, e.seq AS seq ORDER BY seq",
        case_id=case_id)


def get_period_totals(case_id: str, year: int, run=run_read) -> dict:
    """Totals for the accounting equation. Zero until the ledger stores amounts (Phase 5)."""
    rows = run(
        "MATCH (:Engagement {case_id: $case_id})<-[:IN_ENGAGEMENT]-(d:SourceDocument "
        "{doc_type: 'balance_sheet', period_year: $year}) RETURN count(d) AS docs",
        case_id=case_id, year=year)
    return {"assets": 0.0, "liabilities": 0.0, "capital": 0.0, "year": year,
            "documents": rows[0]["docs"] if rows else 0}
