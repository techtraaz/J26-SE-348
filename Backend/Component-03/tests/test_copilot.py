from app.schemas.copilot import CopilotQuery
from app.services import copilot
from app.services.kg_client import KGClient
import pytest


def test_intents():
    assert copilot.answer(CopilotQuery(text="what is the rule limit?")).intent == "rule_query"
    assert copilot.answer(CopilotQuery(text="add new bill to case")).intent == "evidence_append"
    assert copilot.answer(CopilotQuery(text="check this year books")).intent == "fresh_audit"


def test_free_cypher_blocked():
    kg = KGClient()
    with pytest.raises(ValueError):
        kg.get_evidence_chain("MATCH (n) RETURN n")
