from typing import Any

from neo4j import Driver, GraphDatabase
from neo4j.exceptions import DriverError, Neo4jError

from app.config import get_settings

_driver: Driver | None = None


def get_driver() -> Driver:
    global _driver
    if _driver is None:
        s = get_settings()
        _driver = GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_username, s.neo4j_password))
    return _driver


def close_driver() -> None:
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


# neo4j Date / DateTime values become ISO strings so results can go straight to JSON
def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if hasattr(value, "iso_format"):
        return value.iso_format()
    return value


def run_read(query: str, **params: Any) -> list[dict]:
    records, _, _ = get_driver().execute_query(
        query, params, database_=get_settings().neo4j_database, routing_="r"
    )
    return [_plain(r.data()) for r in records]


def run_write(query: str, **params: Any) -> list[dict]:
    records, _, _ = get_driver().execute_query(
        query, params, database_=get_settings().neo4j_database, routing_="w"
    )
    return [r.data() for r in records]


def ping() -> bool:
    try:
        get_driver().verify_connectivity()
        return True
    except (DriverError, Neo4jError, ValueError):
        return False
