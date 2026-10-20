"""Chat sessions on top of the Copilot: saving turns, memory, history.

- converse():      answer a Copilot request inside a session, save both
                   messages and update the session memory
- record_audit():  a Library audit lands in the case's chat
- post_to_case():  another component (C4 report ready) writes into every chat
                   of a case; it only needs the case_id it already knows
- history():       messages, with saved findings filled in from their audit version

A case's own chat has session_id == case_id (one chat per case for now).
"""
import uuid

from app.schemas.chat import ChatMessage, ChatSession, ExternalMessage, MessageRefs
from app.schemas.copilot import CopilotQuery, CopilotResponse
from app.schemas.findings import AuditResult, Finding, now_iso
from app.services import copilot
from app.services.chat_store import ChatStore
from app.services.copilot import memory as memory_rules
from app.services.kg_client import KGClient
from app.services.store import ResultStore

GENERAL_TITLE = "General questions"


def _id() -> str:
    return uuid.uuid4().hex


def open_session(chats: ChatStore, session_id: str, case_id: str | None = None) -> ChatSession:
    """The session, created on first use. A new session named after a case belongs to it."""
    session = chats.get_session(session_id)
    if session is None:
        owner = case_id if case_id == session_id else None
        session = ChatSession(session_id=session_id, case_id=owner, title=owner or GENERAL_TITLE)
        chats.save_session(session)
    return session


def _refs(response: CopilotResponse) -> tuple[MessageRefs | None, list[Finding]]:
    """Saved findings by reference; unsaved (what-if) findings inline."""
    data = response.data or {}
    findings = data.get("findings") or []
    if not findings:
        return None, []
    if data.get("unsaved"):
        return None, [Finding.model_validate(f) for f in findings]
    version = data.get("version") or data.get("to")
    return MessageRefs(version=version, finding_ids=[f["finding_id"] for f in findings]), []


def converse(q: CopilotQuery, kg: KGClient, store: ResultStore, chats: ChatStore) -> CopilotResponse:
    # A chat whose id is an audited case's id is that case's chat.
    owner = q.case_id or (q.session_id if store.latest(q.session_id) else None)
    session = open_session(chats, q.session_id, owner)
    query = q.model_copy(update={"case_id": q.case_id or session.case_id})
    response = copilot.answer(query, kg, store, memory=session.context)
    data = response.data or {}
    case_id = data.get("case_id")
    chats.add_message(ChatMessage(
        message_id=_id(), session_id=session.session_id, case_id=case_id, role="user", text=q.text,
        data={"attached_docs": len(q.docs)} if q.docs else {}))
    refs, inline = _refs(response)
    chats.add_message(ChatMessage(
        message_id=_id(), session_id=session.session_id, case_id=case_id, role="copilot",
        text=response.reply, intent=response.intent, group=response.group,
        suggestions=response.suggestions, refs=refs, findings=inline,
        data={"routing": data["nlu"]} if data.get("nlu") else {}))
    session.context = memory_rules.update(session.context, response)
    session.updated_at = now_iso()
    chats.save_session(session)
    return response.model_copy(update={"session_id": session.session_id})


def audit_text(result: AuditResult) -> str:
    if result.status == "not_auditable":
        return f"Case {result.case_id} version {result.version} is not auditable. The reasons are below."
    rule = [f for f in result.findings if not f.rule_id.startswith("REV-")]
    reviews = sum(f.review_status == "needs_more_evidence" for f in result.findings)
    high = sum(f.severity == "high" for f in rule)
    text = (f"Case {result.case_id} version {result.version} saved: {len(rule)} rule finding(s) "
            f"({high} high), {reviews} need review.")
    if result.rejected_records:
        text += f" Rejected documents: {', '.join(result.rejected_records)}."
    return text


def record_audit(chats: ChatStore, session_id: str, result: AuditResult) -> None:
    """An audit run outside the chat (e.g. from the Library) shows up in it."""
    text = audit_text(result)
    session = open_session(chats, session_id, result.case_id)
    chats.add_message(ChatMessage(
        message_id=_id(), session_id=session_id, case_id=result.case_id, role="copilot", text=text,
        intent="audit_run", group="fresh_audit",
        refs=MessageRefs(version=result.version, finding_ids=[f.finding_id for f in result.findings]),
        suggestions=["Show the high severity findings", "What evidence is missing?"]))
    session.context = session.context.model_copy(update={
        "case_id": result.case_id, "version": result.version, "last_intent": "audit_run",
        "finding_ids": [f.finding_id for f in result.findings]})
    session.updated_at = now_iso()
    chats.save_session(session)


def post_to_case(chats: ChatStore, case_id: str, msg: ExternalMessage) -> list[ChatMessage]:
    """Write into every chat of the case; create the case's own chat if it has none."""
    sessions = chats.list_sessions(case_id=case_id) or [open_session(chats, case_id, case_id)]
    out = []
    for session in sessions:
        m = ChatMessage(message_id=_id(), session_id=session.session_id, case_id=case_id,
                        role=msg.role, text=msg.text, source=msg.source, data=msg.data,
                        refs=MessageRefs(version=msg.version) if msg.version else None)
        out.append(chats.add_message(m))
        session.updated_at = now_iso()
        chats.save_session(session)
    return out


def history(chats: ChatStore, store: ResultStore, session_id: str,
            before: int | None = None, limit: int = 50) -> list[ChatMessage]:
    """Messages oldest first, with referenced findings read from their saved version.
    Saved versions never change, so a reference always shows what was said then."""
    messages = chats.messages(session_id, before, limit)
    records: dict[tuple[str, int], dict | None] = {}
    for m in messages:
        if not (m.refs and m.refs.version and m.refs.finding_ids and m.case_id):
            continue
        key = (m.case_id, m.refs.version)
        if key not in records:
            records[key] = store.get(*key)
        rec = records[key]
        if rec is None:
            m.data = {**m.data, "refs_missing": True}
            continue
        by_id = {f["finding_id"]: f for f in rec["findings"]}
        m.findings = [Finding.model_validate(by_id[i]) for i in m.refs.finding_ids if i in by_id]
    return messages
