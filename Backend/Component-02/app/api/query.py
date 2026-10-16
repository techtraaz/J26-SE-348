from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from neo4j.exceptions import ClientError, CypherSyntaxError, DriverError, Forbidden, Neo4jError
from pydantic import BaseModel, Field

from app.config import get_settings
from app.query import contract, cypher, lookup, search

router = APIRouter(prefix="/query", tags=["kg query"])


def _call(fn, *args):
    try:
        return fn(*args)
    except (DriverError, Neo4jError) as exc:
        raise HTTPException(503, f"Neo4j unavailable: {exc}") from exc


@router.get("/rules/{doc_type}")
def rules(doc_type: str) -> list[dict]:
    """KGClient.get_rules: policy rules with limits."""
    return _call(contract.get_rules, doc_type)


@router.get("/check-rules/{doc_type}")
def check_rules(doc_type: str) -> list[dict]:
    """KGClient.get_check_rules: machine-checkable rules for a document type."""
    return _call(contract.get_check_rules, doc_type)


@router.get("/evidence-chain/{doc_id}")
def evidence_chain(doc_id: str) -> list[str]:
    """KGClient.get_evidence_chain: the document and its linked documents."""
    return _call(contract.get_evidence_chain, doc_id)


@router.get("/postings/{case_id}")
def postings(case_id: str) -> list[dict]:
    """KGClient.get_postings."""
    return _call(contract.get_postings, case_id)


@router.get("/period-totals/{case_id}")
def period_totals(case_id: str, year: int) -> dict:
    """KGClient.get_period_totals."""
    return _call(contract.get_period_totals, case_id, year)


@router.get("/fields")
def fields() -> dict[str, str]:
    """Document field name or alias -> line item code, e.g. capital -> total_equity."""
    return _call(contract.field_map)


def _found(value, what: str):
    if not value:
        raise HTTPException(404, f"{what} not found")
    return value


@router.get("/rules/{rule_id}/explain")
def explain_rule(rule_id: str) -> dict:
    """Why a rule exists, with the paragraphs it comes from and a ready-made sentence."""
    return _found(_call(lookup.explain_rule, rule_id), f"Rule {rule_id}")


@router.get("/standards/{code}")
def standard(code: str) -> dict:
    return _found(_call(lookup.get_standard, code), f"Standard {code}")


@router.get("/sections/{section_id}")
def section(section_id: str) -> dict:
    """A paragraph, e.g. LKAS 2:9, with its requirements, definitions, links and amendments."""
    return _found(_call(lookup.get_section, section_id), f"Section {section_id}")


@router.get("/line-items/{code}")
def line_item(code: str) -> dict:
    """A line item by code or alias, with its statement, class, standards and equations."""
    return _found(_call(lookup.get_line_item, code), f"Line item {code}")


@router.get("/equations")
def equations(statement: str | None = None, kind: str | None = None) -> list[dict]:
    return _call(lookup.list_equations, statement, kind)


@router.get("/definitions/{term}")
def definition(term: str) -> list[dict]:
    return _found(_call(lookup.get_definition, term), f"Definition {term}")


@router.get("/search")
def search_standards(q: Annotated[str, Query(min_length=2, max_length=500)],
                     mode: Literal["keyword", "semantic", "hybrid"] = "hybrid",
                     limit: Annotated[int, Query(ge=1, le=50)] = 10,
                     standard: str | None = None) -> dict:
    """Search the standards. A paragraph reference such as 'LKAS 2:9' goes straight to it."""
    return _call(search.search, q, mode, limit, standard)


class CypherRequest(BaseModel):
    query: str = Field(min_length=1, max_length=5000)
    params: dict = Field(default_factory=dict)


@router.post("/cypher")
def run_cypher(body: CypherRequest) -> dict:
    """Read-only Cypher for people. Agents use the fixed endpoints above."""
    if not get_settings().query_cypher_enabled:
        raise HTTPException(403, "Cypher endpoint is disabled (QUERY_CYPHER_ENABLED=false)")
    try:
        return cypher.run_checked(body.query, body.params)
    except cypher.CypherRejected as exc:
        raise HTTPException(400, str(exc)) from exc
    except CypherSyntaxError as exc:
        raise HTTPException(400, f"Cypher syntax error: {exc.message}") from exc
    except Forbidden as exc:
        raise HTTPException(403, f"Refused by Neo4j: {exc.message}") from exc
    except ClientError as exc:
        status = 408 if "timedout" in (exc.code or "").lower().replace(" ", "") else 400
        raise HTTPException(status, f"{exc.code}: {exc.message}") from exc
    except (DriverError, Neo4jError) as exc:
        raise HTTPException(503, f"Neo4j unavailable: {exc}") from exc
