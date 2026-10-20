"""What C4 (XAI timeline, report generator) needs from C3: every rule applied
with the same facts as its live step, document names, chat routing decisions,
whether the run's steps were all queued, and audits of C1 documents by id."""
import mongomock
import pytest
from fastapi.testclient import TestClient

from app import main
from app.schemas.copilot import CopilotQuery
from app.services import c1_fetch, copilot, intake, llm, orchestrator
from app.services.store import MongoStore
from tests.conftest import doc
from tests.test_c1_review import _stamp
from tests.test_copilot import FakeLLM

client = TestClient(main.app)


def _audit(kg, store, docs, case_id="C4-1"):
    return orchestrator.run_case(intake.normalize_case({"case_id": case_id, "docs": docs}), kg, store=store)


def _mongo():
    return MongoStore(uri="mongodb://fake", db_name="xai", client=mongomock.MongoClient())


def _steps(store, kind=None):
    assert store.trace_exporter().flush(timeout=5)
    events = store.traces_collection().find({"event_type": "step"}, {"_id": 0}, sort=[("seq", 1)])
    return [e for e in events if kind is None or e["kind"] == kind]


# --- rules applied: the record of every rule, same facts as the live steps ----------------

def test_every_rule_run_is_recorded_with_its_values(kg, store):
    r = _audit(kg, store, [
        doc("SFP-41", "balance_sheet", {"total_assets": 152733375, "total_liabilities": 67133250,
                                        "total_equity": 85600125}, name="01_SFP_Wk41.pdf"),
        doc("SFP-42", "balance_sheet", {"total_assets": 164673550, "total_liabilities": 67832630,
                                        "total_equity": 84778770}, name="02_SFP_Wk42.pdf")])
    chk = {a.doc_id: a for a in r.rules_applied if a.rule_id == "CHK-001"}
    assert chk["SFP-41"].outcome == "passed" and chk["SFP-41"].finding_id is None
    assert chk["SFP-42"].outcome == "failed" and chk["SFP-42"].finding_id == "SFP-42-CHK-001"
    assert chk["SFP-42"].values == {"assets": 164673550.0, "liabilities": 67832630.0, "capital": 84778770.0}
    assert chk["SFP-42"].detail == "assets 164,673,550.00 vs liabilities + capital 152,611,400.00"
    assert chk["SFP-42"].sides == {"left": "assets", "op": "==", "right": "liabilities + capital",
                                   "left_value": 164673550.0, "right_value": 152611400.0}
    assert (chk["SFP-42"].rule_name, chk["SFP-42"].doc_type) == ("Accounting equation", "balance_sheet")
    assert chk["SFP-42"].reason.startswith("Accounting equation failed for 02_SFP_Wk42.pdf")
    skipped = next(a for a in r.rules_applied if a.rule_id == "CHK-007")
    assert skipped.outcome == "skipped" and skipped.reason.startswith("missing ")
    assert not any(t.decision_type == "rule" for t in r.trace)  # the live steps show them instead


def test_live_rule_steps_carry_the_same_facts_as_rules_applied(kg):
    store = _mongo()
    r = _audit(kg, store, [doc("SFP-42", "balance_sheet", {"total_assets": 164673550,
                                                           "total_liabilities": 67832630,
                                                           "total_equity": 84778770}),
                           doc("INV", "invoice", {"amount": 636256, "approvals": 1})])
    live = {(s["facts"]["rule_id"], s["facts"]["doc_id"]): s for s in _steps(store)
            if s["kind"] in ("rule_check", "policy_check")}
    for a in r.rules_applied:
        if a.kind == "policy_check" and a.outcome == "skipped":
            continue  # a limit that could not be compared is not on the timeline
        s = live[(a.rule_id, a.doc_id)]
        assert (s["kind"], s["status"]) == (a.kind, a.outcome)
        if a.kind == "rule_check":
            assert (s["facts"]["sides"], s["facts"]["values"], s["facts"]["reason"]) == (a.sides, a.values, a.reason)
        else:
            assert (s["facts"]["approvals_signed"], s["facts"]["limit"]) == (a.approvals_signed, a.limit)


@pytest.mark.parametrize("fields,outcome", [
    ({"amount": 50000}, "passed"),                      # within the limit
    ({"amount": 2562724, "approvals": 2}, "passed"),    # above it, both approvals signed
    ({"amount": 636256, "approvals": 1}, "failed"),     # Director approval blank
    ({"amount": 636256}, "review"),                     # stamp not read: confirm it
])
def test_policy_rule_outcomes(kg, store, fields, outcome):
    r = _audit(kg, store, [doc("INV", "invoice", fields)])
    pol = next(a for a in r.rules_applied if a.rule_id == "POL-07")
    assert pol.outcome == outcome and pol.expression == "amount <= 100000"
    assert (pol.finding_id is not None) == (outcome in ("failed", "review"))


def test_policy_rule_without_an_amount_is_skipped(kg):
    from app.services import rules
    d = intake.normalize_case({"case_id": "X", "docs": [doc("INV", "invoice", {"purchase_basis": "credit"})]}).docs[0]
    found, applied = rules.policy_check(d, kg.get_rules("invoice"))
    assert found == [] and [a.outcome for a in applied] == ["skipped"]


def test_saved_record_has_names_and_rules_for_the_report(kg, store):
    _audit(kg, store, [doc("INV-04", "invoice", {"amount": 636256, "approvals": 1},
                           name="04_Tax_Invoice_COI-INV-26-1158.pdf")])
    rec = store.latest("C4-1")
    assert rec["case"]["docs"][0]["name"] == "04_Tax_Invoice_COI-INV-26-1158.pdf"
    assert {a["rule_id"] for a in rec["rules_applied"]} >= {"POL-07", "CHK-005"}


def test_not_auditable_case_applies_no_rules(kg, store):
    r = _audit(kg, store, [])
    assert r.status == "not_auditable" and r.rules_applied == [] and r.findings


def test_bad_document_name_is_rejected():
    with pytest.raises(intake.IntakeError):
        intake.normalize_case({"case_id": "X", "docs": [doc("D", "invoice", {}, name=["x"])]})


# --- conversation and routing ---------------------------------------------------------------

@pytest.mark.parametrize("text,intent", [
    ("hey", "greeting"), ("Good morning!", "greeting"), ("hello copilot", "greeting"),
    ("thanks", "thanks"), ("ok great, thank you", "thanks"),
    ("what's the weather today?", "out_of_scope"), ("tell me a joke", "out_of_scope"),
    ("what can you do?", "help"),
    ("hi, list the high findings for case ACME-1", "list_findings"),  # a greeting inside a request
])
def test_conversation_intents(store, kg, text, intent):
    assert copilot.answer(CopilotQuery(text=text), kg, store).intent == intent


def test_greeting_mentions_the_current_case(kg, store):
    _audit(kg, store, [doc("INV", "invoice", {"amount": 636256, "approvals": 1})], case_id="ACME-1")
    r = copilot.answer(CopilotQuery(text="hey", case_id="ACME-1"), kg, store)
    assert r.reply.startswith("Hello!") and "case ACME-1 (version 1" in r.reply
    assert "I can't help" in copilot.answer(CopilotQuery(text="tell me a joke"), kg, store).reply


def test_routing_goes_to_c4_and_into_the_chat(kg):
    store = _mongo()
    assert copilot.answer(CopilotQuery(text="hey", session_id="S-ROUTE"), kg, store).intent == "greeting"
    assert store.trace_exporter().flush(timeout=5)
    nlu = store.traces_collection().find_one({"event_type": "copilot_nlu"})
    assert nlu["case_id"] == "S-ROUTE" and nlu["intent"] == "greeting"
    assert nlu["routing"]["method"] == "rules" and nlu["routing"]["rules_scores"]["greeting"] == 3.0
    assert nlu["routing"]["rules_confident"] is True


def test_routing_is_saved_on_the_chat_message():
    client.post("/copilot/query", json={"text": "hey", "session_id": "S-ROUTE"})
    saved = client.get("/chat/S-ROUTE/messages").json()
    reply = next(m for m in saved["messages"] if m["role"] == "copilot")
    assert reply["data"]["routing"]["rules_intent"] == "greeting"


# --- events_published: were all of the run's steps queued for C4? -------------------------

def test_events_published_when_every_step_was_queued(kg):
    store = _mongo()
    r = _audit(kg, store, [doc("INV", "invoice", {"amount": 636256, "approvals": 1})])
    assert r.events_published is True and not any(t.agent_name == "events" for t in r.trace)
    assert store.latest("C4-1")["events_published"] is True


def test_no_tracing_is_not_published_and_says_why(kg, store):
    r = _audit(kg, store, [doc("INV", "invoice", {"amount": 636256, "approvals": 1})])
    assert r.events_published is False
    note = next(t.detail for t in r.trace if t.agent_name == "events")
    assert "XAI tracing is off" in note and "tracing is off" in store.latest("C4-1")["trace"][-1]["detail"]


def test_dropped_steps_are_not_published_and_say_why(kg):
    store = _mongo()
    exporter = store.trace_exporter()
    exporter._blocked_until = float("inf")  # MongoDB in its retry pause: every event is refused
    r = _audit(kg, store, [doc("INV", "invoice", {"amount": 636256, "approvals": 1})])
    assert r.events_published is False
    assert "were dropped" in next(t.detail for t in r.trace if t.agent_name == "events")
    assert any(f.rule_id == "POL-07" for f in r.findings)  # the audit itself is unaffected


# --- audit of C1 documents fetched by id ----------------------------------------------------

def fake_c1(records: dict[str, dict], down: bool = False):
    """A transport answering like C1's document and /verified endpoints."""
    def get(path: str):
        if down:
            raise c1_fetch.C1Unavailable("refused")
        parts = path.strip("/").split("/")  # api, v1, documents, id[, verified]
        rec = records.get(parts[3])
        if rec is None:
            return None
        if len(parts) == 5:
            return rec.get("verified")
        return {"id": parts[3], "filename": rec["filename"], "status": rec["status"]}
    return get


@pytest.fixture
def c1(monkeypatch):
    real = c1_fetch.C1Client

    def use(records, down=False):
        monkeypatch.setattr(c1_fetch, "C1Client",
                            lambda: real("http://c1", transport=fake_c1(records, down)))
    return use


def test_audit_by_c1_document_id(c1):
    c1({"inv-04": {"filename": "04_Tax_Invoice_COI-INV-26-1158.pdf", "status": "verified",
                   "verified": {**_stamp(""), "document_id": "inv-04"}}})
    r = client.post("/audit/run/c1", json={"case_id": "C1-RUN", "documents": [{"document_id": "inv-04"}]})
    assert r.status_code == 200, r.text
    body = r.json()
    pol = next(f for f in body["findings"] if f["rule_id"] == "POL-07")
    assert pol["severity"] == "high"  # 1 of 2 approvals signed
    assert next(a for a in body["rules_applied"] if a["rule_id"] == "POL-07")["outcome"] == "failed"
    saved = client.get("/audit/C1-RUN/latest").json()
    assert saved["case"]["docs"][0]["name"] == "04_Tax_Invoice_COI-INV-26-1158.pdf"
    assert saved["case"]["docs"][0]["source"]["verified_version"] == 2


@pytest.mark.parametrize("records,down,status", [
    ({}, False, 404),                                                     # unknown in C1
    ({"inv-04": {"filename": "x.pdf", "status": "needs_review"}}, False, 422),  # not verified yet
    ({}, True, 502),                                                      # C1 down
])
def test_audit_by_c1_id_errors(c1, records, down, status):
    c1(records, down)
    r = client.post("/audit/run/c1", json={"case_id": "C1-ERR", "documents": [{"document_id": "inv-04"}]})
    assert r.status_code == status, r.text


# --- the case summary written by the LLM ---------------------------------------------------

@pytest.fixture
def summary_llm():
    def use(reply):
        provider = FakeLLM(reply)
        llm.use_provider(provider)
        return provider
    yield use
    llm.use_provider(None)


SFP_42 = doc("SFP-42", "balance_sheet", {"total_assets": 164673550, "total_liabilities": 67832630,
                                          "total_equity": 84778770}, name="02_SFP_Wk42.pdf")


def test_failed_comparison_states_its_difference(kg, store):
    chk = next(f for f in _audit(kg, store, [SFP_42]).findings if f.rule_id == "CHK-001")
    assert chk.message.endswith("Difference: 12,062,150.00.")


def test_llm_summary_uses_only_the_facts(kg, store, summary_llm):
    provider = summary_llm("Case C4-1: the statement 02_SFP_Wk42.pdf does not balance.\n"
                        "- CHK-001 failed: assets 164,673,550 exceed liabilities plus capital by "
                        "12,062,150 (CF:4.4). Check the ledger for unposted entries.")
    r = _audit(kg, store, [SFP_42])
    summary = next(t for t in r.trace if t.decision_type == "summary")
    assert "12,062,150" in summary.detail and "unposted entries" in summary.detail
    system, facts, _ = provider.calls[-1]
    assert "never add numbers" in system and "02_SFP_Wk42.pdf" in facts and "Difference: 12,062,150.00" in facts


@pytest.mark.parametrize("reply", [
    "Assets exceed liabilities by Rs 9,999,999.",  # a number not in the facts
    "This breaks GDPR.",                           # a banned word
    "x" * 5000,                                    # too long
])
def test_unsafe_summary_is_dropped_and_said_so(kg, store, summary_llm, reply):
    summary_llm(reply)
    r = _audit(kg, store, [SFP_42])
    assert not any(t.decision_type == "summary" for t in r.trace)
    skipped = next(t for t in r.trace if t.decision_type == "summary_skipped")
    assert "not in the facts" in skipped.detail
    assert any(f.rule_id == "CHK-001" and f.severity == "high" for f in r.findings)  # findings untouched


def test_no_llm_no_summary_but_a_note(kg, store):
    r = _audit(kg, store, [SFP_42])
    assert "LLM is turned off" in next(t.detail for t in r.trace if t.decision_type == "summary_skipped")


# --- the chat message an audit leaves --------------------------------------------------

INV_CASE = [doc("INV-03", "invoice", {"amount": 2562724, "approvals": 2}, name="03_Tax_Invoice.pdf"),
            doc("PO-03a", "purchase_order", {"amount": 2562724}, name="03a_Purchase_Order.pdf",
                parent_doc_id="INV-03"),
            doc("GRN-03b", "goods_received_note", {}, name="03b_Goods_Received_Note.pdf",
                parent_doc_id="INV-03")]


def test_audit_reply_says_what_was_checked_on_each_document(kg, store):
    from app.services import audit_reply
    r = _audit(kg, store, INV_CASE)
    text = audit_reply.describe_saved(r, store)
    assert text.startswith("Audit of case C4-1 saved as version 1. 3 documents checked. "
                           "No audit rule was broken. 1 item needs your review.")
    assert "03_Tax_Invoice.pdf (invoice, 2026)" in text
    assert ("- POL-07 Purchases above Rs. 100,000 need dual approval: passed "
            "(amount 2,562,724.00 > limit 100,000.00; 2 of 2 approvals signed)") in text
    assert "03a_Purchase_Order.pdf (purchase order, 2026, supports 03_Tax_Invoice.pdf)" in text
    assert ("- CHK-003 Child amount matches parent: passed "
            "(child.amount 2,562,724.00 vs parent.amount 2,562,724.00)") in text
    assert "- Needs review (REV-004): No fields were extracted for 03b_Goods_Received_Note.pdf" in text
    assert "GRN-03b;" not in text  # people see file names, not ids


def test_audit_reply_for_a_case_that_cannot_be_audited(kg, store):
    from app.services import audit_reply
    r = _audit(kg, store, [])
    assert "is not auditable" in audit_reply.describe_saved(r, store)


@pytest.mark.parametrize("text", ["audit it again", "audit this", "check it again please"])
def test_audit_again_on_an_audited_case_reruns_it(kg, store, text):
    _audit(kg, store, INV_CASE, case_id="AGAIN-1")
    r = copilot.answer(CopilotQuery(text=text, case_id="AGAIN-1"), kg, store)
    assert r.intent == "rerun_audit" and store.latest("AGAIN-1")["version"] == 2
    assert r.reply.startswith("Audit of case AGAIN-1 saved as version 2.")


def test_audit_with_nothing_attached_asks_in_plain_words(kg, store):
    r = copilot.answer(CopilotQuery(text="audit these documents", case_id="NEW-9"), kg, store)
    assert r.data["needs"] == "docs" and "Attach them with +" in r.reply and "POST" not in r.reply
