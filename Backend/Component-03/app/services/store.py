"""Audit result store (FR6): every run of a case is a new version; old versions
are never overwritten.

One record per run, shared with Component-04 (same MongoDB database):
  _id "<case_id>:v<version>", every AuditResult field at the top level, plus
  "case": the exact input case that version was computed from.
Version numbers come from an atomic per-case counter, so concurrent runs never
get the same number.

MongoStore fails loudly (StoreError) when MongoDB cannot be used; the API then
answers 503 instead of returning a result that was not saved.
"""
import threading

from app import config
from app.schemas.case import AuditCase
from app.schemas.findings import AuditResult, TraceEntry


class StoreError(RuntimeError):
    """The result store cannot be read or written."""


class ResultStore:
    def next_version(self, case_id: str) -> int: raise NotImplementedError
    def save(self, case: AuditCase, result: AuditResult) -> None: raise NotImplementedError
    def set_events(self, case_id: str, version: int, published: bool,
                   note: str | None) -> None:
        """Record the C4 event outcome, known only after pipeline_end was sent."""
        raise NotImplementedError
    def get(self, case_id: str, version: int) -> dict | None: raise NotImplementedError
    def latest(self, case_id: str) -> dict | None: raise NotImplementedError
    def versions(self, case_id: str) -> list[dict]: raise NotImplementedError
    def latest_all(self, limit: int = 200) -> list[dict]:
        """Newest version of every case, newest first."""
        raise NotImplementedError


def _record(case: AuditCase, result: AuditResult) -> dict:
    return {"_id": f"{result.case_id}:v{result.version}", **result.model_dump(),
            "case": case.model_dump()}


def _events_entry(note: str) -> dict:
    return TraceEntry(agent_name="events", decision_type="events", detail=note).model_dump()


def _summary(rec: dict) -> dict:
    return {"version": rec["version"], "status": rec["status"],
            "created_at": rec["created_at"], "findings": len(rec.get("findings", [])),
            "docs": len(rec.get("case", {}).get("docs", []))}


def case_summary(rec: dict) -> dict:
    """One line per case for lists: newest version, status and finding counts."""
    findings = rec.get("findings", [])
    rule = [f for f in findings if not f["rule_id"].startswith("REV-")]
    return {"case_id": rec["case_id"], "version": rec["version"], "status": rec["status"],
            "created_at": rec["created_at"], "docs": len(rec.get("case", {}).get("docs", [])),
            "findings": len(rule), "high": sum(f["severity"] == "high" for f in rule),
            "needs_review": sum(f["review_status"] == "needs_more_evidence" for f in findings)}


class MemoryStore(ResultStore):
    """Process-only store for tests and offline development."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._records: dict[str, dict[int, dict]] = {}

    def next_version(self, case_id):
        with self._lock:
            self._counters[case_id] = self._counters.get(case_id, 0) + 1
            return self._counters[case_id]

    def save(self, case, result):
        with self._lock:
            runs = self._records.setdefault(result.case_id, {})
            if result.version in runs:
                raise StoreError(f"version {result.version} of {result.case_id} already saved")
            runs[result.version] = _record(case, result)

    def set_events(self, case_id, version, published, note):
        with self._lock:
            rec = self._records[case_id][version]
            rec["events_published"] = published
            if note:
                rec["trace"] = [*rec["trace"], _events_entry(note)]

    def get(self, case_id, version):
        rec = self._records.get(case_id, {}).get(version)
        return dict(rec) if rec else None

    def latest(self, case_id):
        runs = self._records.get(case_id, {})
        return dict(runs[max(runs)]) if runs else None

    def versions(self, case_id):
        return [_summary(r) for _, r in sorted(self._records.get(case_id, {}).items())]

    def latest_all(self, limit=200):
        with self._lock:
            newest = [dict(runs[max(runs)]) for runs in self._records.values() if runs]
        return sorted(newest, key=lambda r: r["created_at"], reverse=True)[:limit]


class MongoConnection:
    """One lazily opened MongoDB client, shared by the result and chat stores.
    Every failure becomes StoreError, so callers never see driver exceptions."""

    def __init__(self, uri: str | None = None, db_name: str | None = None, client=None) -> None:
        self._uri = config.MONGODB_URI if uri is None else uri
        self._db_name = db_name or config.MONGODB_DB
        self._client = client
        self._indexes: set[str] = set()
        self._lock = threading.Lock()

    def db(self):
        with self._lock:
            if self._client is None:
                if not self._uri:
                    raise StoreError("C03_MONGODB_URI is not configured")
                from pymongo import MongoClient
                self._client = MongoClient(self._uri, serverSelectionTimeoutMS=config.MONGODB_TIMEOUT_MS,
                                           appname="nomos-c03")
            return self._client[self._db_name]

    def run(self, fn):
        from pymongo.errors import PyMongoError
        try:
            return fn(self.db())
        except PyMongoError as exc:
            raise StoreError(f"MongoDB error: {exc}") from exc

    def ensure_index(self, collection: str, keys: list, **options) -> None:
        key = f"{collection}:{keys}"
        if key not in self._indexes:
            self.run(lambda db: db[collection].create_index(keys, **options))
            self._indexes.add(key)


_mongo: MongoConnection | None = None
_mongo_lock = threading.Lock()


def shared_mongo() -> MongoConnection:
    global _mongo
    with _mongo_lock:
        if _mongo is None:
            _mongo = MongoConnection()
        return _mongo


class MongoStore(ResultStore):
    def __init__(self, uri: str | None = None, db_name: str | None = None,
                 client=None, conn: MongoConnection | None = None) -> None:
        self._conn = conn or MongoConnection(uri, db_name, client)

    def _db(self):
        return self._conn.db()

    def _run(self, fn):
        self._conn.ensure_index(config.RESULTS_COLLECTION, [("case_id", 1), ("version", -1)], unique=True)
        return self._conn.run(fn)

    def next_version(self, case_id):
        from pymongo import ReturnDocument
        doc = self._run(lambda db: db[config.COUNTERS_COLLECTION].find_one_and_update(
            {"_id": case_id}, {"$inc": {"seq": 1}}, upsert=True,
            return_document=ReturnDocument.AFTER))
        return int(doc["seq"])

    def save(self, case, result):
        self._run(lambda db: db[config.RESULTS_COLLECTION].insert_one(_record(case, result)))

    def set_events(self, case_id, version, published, note):
        change: dict = {"$set": {"events_published": published}}
        if note:
            change["$push"] = {"trace": _events_entry(note)}
        self._run(lambda db: db[config.RESULTS_COLLECTION].update_one(
            {"_id": f"{case_id}:v{version}"}, change))

    def get(self, case_id, version):
        return self._run(lambda db: db[config.RESULTS_COLLECTION].find_one(
            {"case_id": case_id, "version": version}))

    def latest(self, case_id):
        return self._run(lambda db: db[config.RESULTS_COLLECTION].find_one(
            {"case_id": case_id}, sort=[("version", -1)]))

    def versions(self, case_id):
        rows = self._run(lambda db: list(db[config.RESULTS_COLLECTION].find(
            {"case_id": case_id},
            {"version": 1, "status": 1, "created_at": 1, "findings.finding_id": 1,
             "case.docs.doc_id": 1}).sort("version", 1)))
        return [_summary(r) for r in rows]

    def latest_all(self, limit=200):
        return self._run(lambda db: list(db[config.RESULTS_COLLECTION].aggregate([
            {"$sort": {"case_id": 1, "version": -1}},
            {"$group": {"_id": "$case_id", "rec": {"$first": "$$ROOT"}}},
            {"$replaceRoot": {"newRoot": "$rec"}},
            {"$sort": {"created_at": -1}},
            {"$limit": limit}])))


_store: ResultStore | None = None
_store_lock = threading.Lock()


def default_store() -> ResultStore:
    """One store per process, chosen by C03_STORE_MODE."""
    global _store
    with _store_lock:
        if _store is None:
            mode = config.STORE_MODE.lower()
            if mode not in ("mongo", "memory"):
                raise StoreError(f"Unknown C03_STORE_MODE {mode!r}; use mongo|memory.")
            _store = MongoStore(conn=shared_mongo()) if mode == "mongo" else MemoryStore()
        return _store
