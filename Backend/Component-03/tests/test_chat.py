import mongomock
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.chat import ExternalMessage, SessionContext
from app.schemas.copilot import CopilotQuery
from app.services import chat, intake, orchestrator
from app.services.chat_store import MongoChatStore
from app.services.copilot import memory
from app.services.copilot.entities import extract
from app.services.store import MongoConnection
from tests.conftest import doc

client = TestClient(app)
DOCS = [doc("BS-25", "balance_sheet", {"assets": 100000, "liabilities": 60000, "capital": 40000}, year=2025),
        doc("BS-26", "balance_sheet", {"assets": 180000, "liabilities": 90000, "capital": 60000}),
        doc("INV-9", "invoice", {"amount": 150000, "cash_out": 150000, "purchase_basis": "credit",
                                 "asset_in": 0})]


@pytest.fixture
def acme(kg, store):
    orchestrator.run_case(intake.normalize_case({"case_id": "ACME-1", "docs": DOCS[:2]}), kg, store=store)
    orchestrator.append_evidence("ACME-1", DOCS[2:], kg, store=store)
    return store


def say(kg, store, chats, text, session="ACME-1", case_id=None, docs=None):
    q = CopilotQuery(text=text, session_id=session, case_id=case_id, docs=docs or [])
    return chat.converse(q, kg, store, chats)


# --- saving and memory -----------------------------------------------------------------

def test_turns_are_saved_and_memory_updated(kg, acme, chats):
    r = say(kg, acme, chats, "show the high severity findings")
    assert r.session_id == "ACME-1" and r.intent == "list_findings"
    session = chats.get_session("ACME-1")
    assert session.case_id == "ACME-1"  # a chat named after a case belongs to it
    assert session.context.version == 2 and set(session.context.finding_ids) == {
        f["finding_id"] for f in r.data["findings"]}
    assert session.context.filters.severities == ["high"]
    roles = [m.role for m in chats.messages("ACME-1")]
    assert roles == ["user", "copilot"]
    copilot_msg = chats.messages("ACME-1")[1]
    assert copilot_msg.refs.version == 2 and copilot_msg.findings == []  # stored by reference


def test_follow_up_refers_back_to_the_findings_shown(kg, acme, chats):
    say(kg, acme, chats, "show the findings on invoices")
    r = say(kg, acme, chats, "why did that one fire?")
    assert r.intent == "explain_finding"
    assert {f["rule_id"] for f in r.data["findings"]} <= {"CHK-005", "POL-07"}


def test_follow_up_narrows_the_last_list(kg, acme, chats):
    say(kg, acme, chats, "show the findings on invoices")
    r = say(kg, acme, chats, "only the high ones")
    assert [f["rule_id"] for f in r.data["findings"]] == ["CHK-005"]


def test_general_chat_remembers_the_case(kg, acme, chats):
    say(kg, acme, chats, "what is the status of case ACME-1?", session="GEN-1")
    r = say(kg, acme, chats, "what changed since the last audit?", session="GEN-1")
    assert r.intent == "compare_versions" and r.data["case_id"] == "ACME-1"
    assert chats.get_session("GEN-1").case_id is None  # still a general chat


def test_incomplete_request_does_not_change_memory(kg, acme, chats):
    say(kg, acme, chats, "show the high severity findings")
    before = chats.get_session("ACME-1").context
    say(kg, acme, chats, "explain the rule")  # no rule id: Copilot asks, nothing shown
    assert chats.get_session("ACME-1").context == before


def test_memory_rules():
    ctx = SessionContext(case_id="C", finding_ids=["F1"])
    assert memory.apply(extract("why did it fire?"), "why did it fire?", ctx).finding_ids == ["F1"]
    assert memory.apply(extract("status of this case"), "status of this case", ctx).finding_ids == []
    assert memory.apply(extract("why CHK-001?"), "why CHK-001?", ctx).finding_ids == []


# --- history ----------------------------------------------------------------------------

def test_history_fills_saved_findings_and_keeps_whatif_inline(kg, acme, chats):
    say(kg, acme, chats, "show the high severity findings")
    say(kg, acme, chats, "I paid Rs 180,000 cash, booked on credit, no asset recorded. is that ok?")
    msgs = chat.history(chats, acme, "ACME-1")
    listed, whatif = msgs[1], msgs[3]
    assert {f.rule_id for f in listed.findings} == {"CHK-001", "CHK-005"}
    assert whatif.refs is None and {f.rule_id for f in whatif.findings} == {"CHK-005", "POL-07"}


def test_history_pages_backwards(kg, acme, chats):
    for t in ("summarise this case", "show the audit history", "what evidence is missing?"):
        say(kg, acme, chats, t)
    last_two = chat.history(chats, acme, "ACME-1", limit=2)
    older = chat.history(chats, acme, "ACME-1", before=last_two[0].seq, limit=10)
    assert len(last_two) == 2 and len(older) == 4
    assert [m.seq for m in older + last_two] == [1, 2, 3, 4, 5, 6]
    assert [m.role for m in older + last_two] == ["user", "copilot"] * 3


# --- other components and the Library -----------------------------------------------------

def test_c4_report_reaches_every_chat_of_the_case(kg, acme, chats):
    say(kg, acme, chats, "summarise this case")  # the case's own chat
    say(kg, acme, chats, "status of case ACME-1", session="GEN-1")  # general chat, not the case's
    out = chat.post_to_case(chats, "ACME-1", ExternalMessage(
        text="Standard Audit Report ready.", version=2, data={"report_url": "http://c4/r/1"}))
    assert [m.session_id for m in out] == ["ACME-1"] and out[0].seq > 0
    last = chat.history(chats, acme, "ACME-1")[-1]
    assert last.role == "report" and last.source == "c4" and last.data["report_url"]


def test_c4_report_for_a_case_without_chat_creates_it(chats):
    chat.post_to_case(chats, "NEW-9", ExternalMessage(text="Report ready."))
    assert chats.get_session("NEW-9").case_id == "NEW-9"


def test_api_chat_flow():
    case = {"case_id": "API-C", "docs": [DOCS[2]]}
    assert client.post("/audit/run?session_id=API-C", json=case).status_code == 200
    r = client.post("/copilot/query", json={"text": "show the high severity findings",
                                            "session_id": "API-C"}).json()
    assert r["session_id"] == "API-C" and r["intent"] == "list_findings"
    msgs = client.get("/chat/API-C/messages").json()["messages"]
    assert [m["role"] for m in msgs] == ["copilot", "user", "copilot"]  # Library audit first
    assert msgs[0]["findings"] and msgs[0]["intent"] == "audit_run"
    sessions = client.get("/chat/sessions").json()["sessions"]
    assert sessions[0]["session_id"] == "API-C" and sessions[0]["context"]["case_id"] == "API-C"
    posted = client.post("/chat/case/API-C/messages", json={"text": "Report ready.", "version": 1})
    assert posted.status_code == 200
    assert client.delete("/chat/API-C").json() == {"deleted": "API-C"}
    assert client.get("/chat/API-C/messages").json()["messages"] == []


def test_api_rejects_bad_session_ids():
    assert client.post("/copilot/query", json={"text": "hi", "session_id": "a/b"}).status_code == 422
    assert client.post("/audit/run?session_id=a%7Bb", json={"case_id": "X", "docs": []}).status_code == 422


def test_stateless_requests_still_work():
    r = client.post("/copilot/query", json={"text": "help"}).json()
    assert r["intent"] == "help" and r["session_id"] is None


# --- MongoDB -----------------------------------------------------------------------------

def test_mongo_chat_store_round_trip(kg, acme):
    chats = MongoChatStore(MongoConnection(uri="mongodb://fake", db_name="t",
                                           client=mongomock.MongoClient()))
    say(kg, acme, chats, "show the high severity findings")
    say(kg, acme, chats, "only the high ones")
    assert len(chats.messages("ACME-1")) == 4
    assert chats.get_session("ACME-1").context.filters.severities == ["high"]
    assert [s.session_id for s in chats.list_sessions(case_id="ACME-1")] == ["ACME-1"]
    assert chats.delete_session("ACME-1") and chats.messages("ACME-1") == []


def test_copilot_reply_keeps_its_trace_id_for_explain(kg, acme, chats):
    r = say(kg, acme, chats, "show the high severity findings")
    reply = [m for m in chats.messages("ACME-1") if m.role == "copilot"][-1]
    assert r.data["trace_id"] and reply.data == {"trace_id": r.data["trace_id"]}
    assert all(not m.data.get("trace_id") for m in chats.messages("ACME-1") if m.role == "user")
