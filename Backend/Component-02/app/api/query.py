from fastapi import APIRouter, HTTPException
from neo4j.exceptions import DriverError, Neo4jError

from app.query import contract

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
