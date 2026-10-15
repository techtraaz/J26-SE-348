"""Fixed KG doors. LLM never writes Cypher — blocked by design."""
import json
from pathlib import Path
from app import config


def _block_free_cypher(text: str) -> None:
    """Raise if anyone tries to pass raw Cypher from LLM output."""
    if not config.ALLOW_FREE_CYPHER:
        low = text.lower()
        for bad in ("match ", "cypher", "create (", "merge (", "detach delete"):
            if bad in low:
                raise ValueError(f"Free Cypher blocked: found '{bad.strip()}'. Use fixed functions only.")


def _load_mock_file() -> dict:
    """Mock data stays in mock_data.json next to this file. Committed in git."""
    path = Path(__file__).with_name("mock_data.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"rules_by_doc_type": {}, "check_rules_by_doc_type": {}}


class KGClient:
    """Mock now, live Neo4j later. Same function names, so agents don't change."""

    def __init__(self, mode: str = "mock"):
        self.mode = mode

    def get_rules(self, doc_type: str) -> list[dict]:
        """POL rules with limits, e.g. dual approval above 100000."""
        data = _load_mock_file()
        return list(data.get("rules_by_doc_type", {}).get(doc_type, []))

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
        data = _load_mock_file()
        return list(data.get("check_rules_by_doc_type", {}).get(doc_type, []))
