"""Shared test fixtures for Component 04 tests.

Provides an isolated SQLite database (in-memory) and a configured
FastAPI test client so tests never touch the real trace_store.db.
"""

from __future__ import annotations

import pytest

from app import config


@pytest.fixture(autouse=True)
def _use_in_memory_db(tmp_path):
    """Override the DATABASE_PATH to a temporary file for every test.

    ``autouse=True`` ensures every test function in the suite gets its
    own fresh database without explicitly requesting this fixture.
    """
    test_db = str(tmp_path / "test_trace_store.db")
    config.DATABASE_PATH = test_db
    yield
