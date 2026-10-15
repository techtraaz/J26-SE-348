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


def run_read(query: str, **params: Any) -> list[dict]:
    records, _, _ = get_driver().execute_query(
        query, params, database_=get_settings().neo4j_database, routing_="r"
    )
    return [r.data() for r in records]


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
