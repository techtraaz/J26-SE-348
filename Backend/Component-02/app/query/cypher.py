import re
import time
from typing import Any

from neo4j import unit_of_work

from app.config import get_settings
from app.graph.neo4j_client import _plain, get_driver

# checked after strings and comments are removed, so "CONTAINS 'set'" is fine
_WRITE = re.compile(
    r"(?<!\.)\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|FOREACH|LOAD\s+CSV|GRANT|DENY|REVOKE|"
    r"ALTER|RENAME|START|STOP|TERMINATE|USE)\b", re.IGNORECASE)
_CALL = re.compile(r"\bCALL\s+([A-Za-z_][\w.]*)?", re.IGNORECASE)
_ALLOWED_CALLS = ("db.index.fulltext.querynodes", "db.index.vector.querynodes", "db.labels",
                  "db.relationshiptypes", "db.propertykeys", "db.schema.visualization")
_STRINGS = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`[^`]*`")
_COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
_HIDDEN = {"embedding"}


class CypherRejected(ValueError):
    pass


def check_query(text: str) -> None:
    bare = _STRINGS.sub("''", _COMMENTS.sub(" ", text))
    if ";" in bare.strip().rstrip(";"):
        raise CypherRejected("Only one statement per request")
    if m := _WRITE.search(bare):
        raise CypherRejected(f"Read-only endpoint: '{m.group(1).upper()}' is not allowed")
    for m in _CALL.finditer(bare):
        name = (m.group(1) or "").lower()
        if not name or name not in _ALLOWED_CALLS:
            raise CypherRejected(f"CALL {m.group(1) or '{...}'} is not allowed; "
                                 f"allowed: {', '.join(_ALLOWED_CALLS)}")


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if k not in _HIDDEN}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def run_readonly(text: str, params: dict | None = None) -> dict:
    """Runs in a read transaction, so the database refuses writes even if the check missed one."""
    s = get_settings()
    query = text.strip().rstrip(";")
    limit = s.query_cypher_max_rows
    started = time.perf_counter()

    @unit_of_work(timeout=s.query_cypher_timeout)
    def work(tx):
        result = tx.run(query, params or {})
        rows, truncated = [], False
        for record in result:
            if len(rows) == limit:
                truncated = True
                break
            rows.append(_clean(_plain(record.data())))
        return list(result.keys()), rows, truncated

    with get_driver().session(database=s.neo4j_database) as session:
        columns, rows, truncated = session.execute_read(work)
    return {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": truncated,
            "ms": round((time.perf_counter() - started) * 1000, 1)}


def run_checked(text: str, params: dict | None = None) -> dict:
    check_query(text)
    return run_readonly(text, params)
