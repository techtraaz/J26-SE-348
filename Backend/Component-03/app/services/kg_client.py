"""Fixed KG doors. LLM never writes Cypher — blocked by design."""
from app import config


def _block_free_cypher(text: str) -> None:
    """Raise if anyone tries to pass raw Cypher from LLM output."""
    if not config.ALLOW_FREE_CYPHER:
        low = text.lower()
        for bad in ("match ", "cypher", "create (", "merge (", "detach delete"):
            if bad in low:
                raise ValueError(f"Free Cypher blocked: found '{bad.strip()}'. Use fixed functions only.")


class KGClient:
    """Mock now, live Neo4j later. Same function names, so agents don't change."""

    def __init__(self, mode: str = "mock"):
        self.mode = mode

    def get_rules(self, doc_type: str) -> list[dict]:
        """POL rules with limits, e.g. dual approval above 100000."""
        if doc_type == "invoice":
            return [{"rule_id": "POL-07",
                     "text": "Purchases above Rs. 100,000 need dual approval.",
                     "limit": 100000}]
        return []

    def get_evidence_chain(self, doc_id: str) -> list[str]:
        """IDs linked to this doc (parent + children). Mock returns itself."""
        _block_free_cypher(doc_id)
        return [doc_id]

    def get_postings(self, case_id: str) -> list[dict]:
        """Postings with account types for debit/credit side check."""
        _block_free_cypher(case_id)
        return []

    def get_period_totals(self, case_id: str, year: int) -> dict:
        """Sums for equation check. Real KG sums ledger later."""
        _block_free_cypher(case_id)
        return {"assets": 0.0, "liabilities": 0.0, "capital": 0.0, "year": year}

    def get_check_rules(self, doc_type: str) -> list[dict]:
        """Step-2 scalable rules as data. Agents run them with generic runner."""
        if doc_type == "balance_sheet":
            return [{"rule_id": "CHK-001", "name": "Accounting equation",
                     "expression": "assets == liabilities + capital",
                     "severity": "high"}]
        return []
