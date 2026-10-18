import json

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.schemas.copilot import CopilotQuery
from app.services import copilot, intake, llm, orchestrator
from app.services.copilot.entities import extract
from app.services.copilot.nlu import understand
from app.services.copilot.registry import REGISTRY
from app.services.llm.providers import LLMError, LLMProvider
from tests.conftest import doc


class FakeLLM(LLMProvider):
    """Replies with a fixed JSON (or raises) and records the prompts."""
    name = "fake"

    def __init__(self, reply: dict | str | Exception):
        super().__init__("http://fake", "fake")
        self.reply, self.calls = reply, []

    def chat(self, system, user, schema, timeout):
        self.calls.append((system, user, schema))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply)


@pytest.fixture
def fake_llm():
    def use(reply):
        provider = FakeLLM(reply)
        llm.use_provider(provider)
        return provider
    yield use
    llm.use_provider(None)


@pytest.fixture
def audited(kg, store):
    docs = [doc("BS-25", "balance_sheet", {"assets": 100000, "liabilities": 60000, "capital": 40000}, year=2025),
            doc("BS-26", "balance_sheet", {"assets": 180000, "liabilities": 90000, "capital": 60000}),
            doc("INV-9", "invoice", {"amount": 150000, "cash_out": 150000, "purchase_basis": "credit",
                                     "asset_in": 0})]
    orchestrator.run_case(intake.normalize_case({"case_id": "ACME-1", "docs": docs[:2]}), kg, store=store)
    orchestrator.append_evidence("ACME-1", docs[2:], kg, store=store)
    return store


def ask(kg, store, text, case_id=None, docs=None):
    return copilot.answer(CopilotQuery(text=text, case_id=case_id, docs=docs or []), kg, store)


# --- entities -----------------------------------------------------------------------

def test_entities_are_literal_and_normalised():
    e = extract("why did chk-4 and POL 7 fire on case ACME-1 version 2? high and fraud bills only")
    assert e.rule_ids == ["CHK-004", "POL-07"] and e.case_ids == ["ACME-1"] and e.versions == [2]
    assert e.severities == ["high"] and e.categories == ["possible_fraud"] and e.doc_types == ["invoice"]
    assert e.amounts == []  # rule numbers, versions and case ids are not money


def test_amounts():
    e = extract("paid Rs. 1,250.50 and 2.5m in 2026, refund (5,000), case C-14 Q3")
    assert [a.value for a in e.amounts] == [1250.5, 2500000.0, -5000.0]


def test_known_ids_are_matched_without_keywords():
    e = extract("add a receipt to acme-1 for inv-9", known_doc_ids=["INV-9"], known_case_ids=["ACME-1"])
    assert e.case_ids == ["ACME-1"] and e.doc_ids == ["INV-9"]


# --- registry and NLU ------------------------------------------------------------------

def test_registry_is_complete():
    assert len(REGISTRY) >= 15
    for spec in REGISTRY.values():
        assert spec.description and spec.examples and spec.group


@pytest.mark.parametrize("text,has_docs,intent", [
    ("what is the dual approval limit for invoices?", False, "rule_lookup"),
    ("explain CHK-004", False, "rule_explain"),
    ("show the high severity findings in case C-1", False, "list_findings"),
    ("compare version 1 and 2 of case C-1", False, "compare_versions"),
    ("add these receipts to case C-1", True, "evidence_append"),
    ("I paid Rs 150,000 cash but booked it on credit, is that ok?", False, "whatif_check"),
])
def test_rules_classifier(text, has_docs, intent, monkeypatch):
    monkeypatch.setattr(config, "COPILOT_NLU", "rules")
    assert understand(text, extract(text), has_docs, None).intent == intent


def test_confident_rules_skip_the_llm(fake_llm):
    provider = fake_llm({"intent": "help"})
    u = understand("explain CHK-004", extract("explain CHK-004"), False, None)
    assert u.intent == "rule_explain" and u.method == "rules" and not provider.calls


def test_unsure_rules_ask_the_llm_among_top_candidates(fake_llm):
    provider = fake_llm({"intent": "case_status"})
    text = "anything I should know about ACME-1?"
    u = understand(text, extract(text, known_case_ids=["ACME-1"]), False, "ACME-1")
    assert u.method == "llm" and u.intent == "case_status"
    schema = provider.calls[0][2]
    assert len(schema["properties"]["intent"]["enum"]) <= config.COPILOT_LLM_CANDIDATES + 1


@pytest.mark.parametrize("reply", [{"intent": "delete_everything"}, "no json here",
                                   LLMError("timeout")])
def test_bad_or_failed_llm_falls_back_to_rules(fake_llm, reply):
    fake_llm(reply)
    text = "anything about it?"
    u = understand(text, extract(text), False, None)
    assert u.method == "rules_fallback" and u.intent in REGISTRY and u.llm_error


# --- handlers over saved audits ------------------------------------------------------------

def test_case_questions(kg, audited):
    s = ask(kg, audited, "what is the status of case ACME-1?")
    assert s.intent == "case_status" and s.group == "case_query" and "version 2" in s.reply
    high = ask(kg, audited, "show the high severity findings", case_id="ACME-1")
    assert {f["rule_id"] for f in high.data["findings"]} == {"CHK-001", "CHK-005"}
    why = ask(kg, audited, "why did CHK-005 fire on INV-9?", case_id="ACME-1")
    assert why.intent == "explain_finding" and "SLAuS 240" in why.reply
    diff = ask(kg, audited, "what changed since the last audit?", case_id="ACME-1")
    assert {f["rule_id"] for f in diff.data["new"]} == {"CHK-005", "POL-07"}
    hist = ask(kg, audited, "show the audit history of case ACME-1")
    assert [v["version"] for v in hist.data["versions"]] == [1, 2]
    fraud = ask(kg, audited, "which cases have possible fraud?")
    assert [c["case_id"] for c in fraud.data["cases"]] == ["ACME-1"]


def test_missing_details_are_asked_for_not_guessed(kg, audited):
    r = ask(kg, audited, "show the high severity findings")
    assert r.data["needs"] == "saved_case" and r.data.get("findings") is None
    r = ask(kg, audited, "what is the status of case NOPE-1?")
    assert "no saved audit" in r.reply


def test_rule_lookup_compares_amount_with_limit(kg, store):
    r = ask(kg, store, "Is Rs 120,000 over the approval limit for bills?")
    assert r.intent == "rule_lookup" and "above the POL-07 limit" in r.reply


def test_whatif_reads_text_runs_checks_and_saves_nothing(kg, store, monkeypatch):
    monkeypatch.setattr(config, "EVENTS_ENABLED", True)  # what-if must still send nothing
    r = ask(kg, store, "I paid Rs 180,000 in cash for a printer but booked it on credit, "
                       "no asset recorded. is that ok?")
    assert r.intent == "whatif_check" and r.group == "fresh_audit"
    assert r.data["read"]["fields"] == {"cash_out": 180000.0, "amount": 180000.0,
                                        "purchase_basis": "credit", "asset_in": 0.0}
    assert {f["rule_id"] for f in r.data["result"]["findings"]} == {"CHK-005", "POL-07"}
    assert store.latest_all() == [] and not r.data["result"]["events_published"]


def test_whatif_rejects_llm_numbers_not_in_the_text(kg, store, fake_llm):
    fake_llm({"liabilities": 300000, "capital": 999999, "doc_type": "balance_sheet"})
    r = ask(kg, store, "what if total of 500,000 and 300,000 for the books?")
    fields = r.data["read"]["fields"]
    assert 999999.0 not in fields.values()


def test_audit_intents_save_versions(kg, store):
    docs = [doc("INV", "invoice", {"amount": 5})]
    fresh = ask(kg, store, "audit these documents", case_id="NEW-1", docs=docs)
    assert fresh.intent == "fresh_audit" and fresh.data["version"] == 1
    added = ask(kg, store, "add this receipt to case NEW-1",
                docs=[doc("RC", "receipt", {"amount": 5}, parent_doc_id="INV")])
    assert added.intent == "evidence_append" and added.data["version"] == 2
    again = ask(kg, store, "re-run case NEW-1")
    assert again.intent == "rerun_audit" and again.data["version"] == 3


def test_api_shape_stays_compatible():
    r = TestClient(app).post("/copilot/query", json={"text": "help"}).json()
    assert {"intent", "group", "reply", "data"} <= r.keys() and r["intent"] == "help"


def test_llm_trace_line_must_only_repeat_given_numbers():
    assert llm.is_safe("3 findings for 2 docs", "case has 3 findings for 2 docs")
    assert not llm.is_safe("3 findings, Rs. 9,000 lost", "case has 3 findings")
    assert not llm.is_safe("breaks GDPR", "x")
