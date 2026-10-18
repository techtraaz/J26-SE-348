"""Chat persistence: sessions and their messages.

MongoDB collections (same database as the audit results, owned by C3):
  c03_chat_sessions  _id = session_id, with the structured session memory
  c03_chat_messages  _id = message_id, ordered by a per-session seq
  c03_chat_counters  _id = session_id, the last seq given out
Other components never write here directly; they post through the C3 API.
"""
import threading

from app import config
from app.schemas.chat import ChatMessage, ChatSession
from app.services.store import MongoConnection, shared_mongo

SESSIONS = "c03_chat_sessions"
MESSAGES = "c03_chat_messages"
COUNTERS = "c03_chat_counters"  # next message seq per session


class ChatStore:
    def get_session(self, session_id: str) -> ChatSession | None: raise NotImplementedError
    def save_session(self, session: ChatSession) -> None: raise NotImplementedError
    def list_sessions(self, limit: int = 100, case_id: str | None = None) -> list[ChatSession]:
        raise NotImplementedError
    def add_message(self, message: ChatMessage) -> ChatMessage:
        """Save with the next seq of its session; returns the saved message."""
        raise NotImplementedError
    def messages(self, session_id: str, before: int | None = None,
                 limit: int = 50) -> list[ChatMessage]:
        """The newest `limit` messages with seq below `before`, oldest first."""
        raise NotImplementedError
    def delete_session(self, session_id: str) -> bool: raise NotImplementedError


class MemoryChatStore(ChatStore):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, ChatSession] = {}
        self._messages: dict[str, list[ChatMessage]] = {}

    def get_session(self, session_id):
        s = self._sessions.get(session_id)
        return s.model_copy(deep=True) if s else None

    def save_session(self, session):
        with self._lock:
            self._sessions[session.session_id] = session.model_copy(deep=True)

    def list_sessions(self, limit=100, case_id=None):
        rows = [s for s in self._sessions.values() if case_id is None or s.case_id == case_id]
        return [s.model_copy(deep=True)
                for s in sorted(rows, key=lambda s: s.updated_at, reverse=True)[:limit]]

    def add_message(self, message):
        with self._lock:
            rows = self._messages.setdefault(message.session_id, [])
            saved = message.model_copy(update={"seq": (rows[-1].seq if rows else 0) + 1}, deep=True)
            rows.append(saved)
            return saved.model_copy(deep=True)

    def messages(self, session_id, before=None, limit=50):
        rows = [m for m in self._messages.get(session_id, [])
                if before is None or m.seq < before]
        return [m.model_copy(deep=True) for m in rows[-limit:]]

    def delete_session(self, session_id):
        with self._lock:
            self._messages.pop(session_id, None)
            return self._sessions.pop(session_id, None) is not None


class MongoChatStore(ChatStore):
    def __init__(self, conn: MongoConnection | None = None) -> None:
        self._conn = conn or shared_mongo()

    def _run(self, fn):
        self._conn.ensure_index(MESSAGES, [("session_id", 1), ("seq", -1)], unique=True)
        self._conn.ensure_index(SESSIONS, [("case_id", 1), ("updated_at", -1)])
        return self._conn.run(fn)

    def get_session(self, session_id):
        doc = self._run(lambda db: db[SESSIONS].find_one({"_id": session_id}))
        return ChatSession.model_validate(doc) if doc else None

    def save_session(self, session):
        doc = session.model_dump()
        self._run(lambda db: db[SESSIONS].replace_one({"_id": session.session_id},
                                                      {"_id": session.session_id, **doc}, upsert=True))

    def list_sessions(self, limit=100, case_id=None):
        query = {} if case_id is None else {"case_id": case_id}
        rows = self._run(lambda db: list(db[SESSIONS].find(query).sort("updated_at", -1).limit(limit)))
        return [ChatSession.model_validate(r) for r in rows]

    def add_message(self, message):
        from pymongo import ReturnDocument
        counter = self._run(lambda db: db[COUNTERS].find_one_and_update(
            {"_id": message.session_id}, {"$inc": {"seq": 1}}, upsert=True,
            return_document=ReturnDocument.AFTER))
        saved = message.model_copy(update={"seq": int(counter["seq"])})
        self._run(lambda db: db[MESSAGES].insert_one({"_id": saved.message_id, **saved.model_dump()}))
        return saved

    def messages(self, session_id, before=None, limit=50):
        query: dict = {"session_id": session_id}
        if before is not None:
            query["seq"] = {"$lt": before}
        rows = self._run(lambda db: list(
            db[MESSAGES].find(query).sort("seq", -1).limit(limit)))
        return [ChatMessage.model_validate(r) for r in reversed(rows)]

    def delete_session(self, session_id):
        self._run(lambda db: db[MESSAGES].delete_many({"session_id": session_id}))
        self._run(lambda db: db[COUNTERS].delete_one({"_id": session_id}))
        return self._run(lambda db: db[SESSIONS].delete_one({"_id": session_id})).deleted_count > 0


_chats: ChatStore | None = None
_chats_lock = threading.Lock()


def default_chat_store() -> ChatStore:
    """One chat store per process, following C03_STORE_MODE like the results."""
    global _chats
    with _chats_lock:
        if _chats is None:
            _chats = MongoChatStore() if config.STORE_MODE.lower() == "mongo" else MemoryChatStore()
        return _chats
