"""Shared test fixtures for Component 04 tests.

Provides an isolated SQLite database (in-memory) and a configured
FastAPI test client so tests never touch the real trace_store.db.
"""

from __future__ import annotations

import mongomock
import pytest

from app import config
from app.services import report_store


@pytest.fixture(autouse=True)
def _use_in_memory_db(tmp_path):
    """Override the DATABASE_PATH to a temporary file for every test.

    ``autouse=True`` ensures every test function in the suite gets its
    own fresh database without explicitly requesting this fixture.
    """
    test_db = str(tmp_path / "test_trace_store.db")
    config.DATABASE_PATH = test_db
    yield


@pytest.fixture(autouse=True)
def _in_memory_mongo():
    """Every test gets an empty in-memory MongoDB: no test reaches a real database."""
    db = mongomock.MongoClient()[config.MONGODB_DB_NAME]
    report_store.use_database(db)
    yield db
    report_store.use_database(None)
