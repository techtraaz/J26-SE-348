"""Shared fixtures for tests that need a database and the full app.

Runs on a temporary SQLite file by default. To run the same tests on real
PostgreSQL, set NOMOS_TEST_DATABASE_URL to an EMPTY throwaway database;
its tables are created and dropped around every test.
"""

import io
import os

import pytest
from PIL import Image

from app.core.config import Settings
from app.db.base import Base
from app.db.session import create_db_engine
from app.schemas.extraction import EngineInfo, ExtractionResult, OCRLine, PageResult

@pytest.fixture
def database_url(tmp_path):
    url = os.environ.get("NOMOS_TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}"
    engine = create_db_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    engine.dispose()
    yield url
    engine = create_db_engine(url)
    Base.metadata.drop_all(engine)
    engine.dispose()

@pytest.fixture
def replay_fixture(tmp_path):
    line = OCRLine(
        text="TOTAL 42.00",
        confidence=0.9731,
        box=(10, 20, 110, 40),
        polygon=[(10, 20), (110, 20), (110, 40), (10, 40)],
    )
    page = PageResult(page_number=1, width=200, height=100, lines=[line], elapsed_ms=51000.0)
    result = ExtractionResult(
        engine=EngineInfo(name="paddleocr", version="3.7.0", settings={}), pages=[page]
    )
    path = tmp_path / "fixture.json"
    path.write_text(result.model_dump_json(), encoding="utf-8")
    return path

@pytest.fixture
def make_settings(tmp_path, database_url, replay_fixture):
    """Build Settings for a test app. The background worker is OFF by default
    so tests drive it deterministically with worker.run_once()."""

    def _make(**overrides) -> Settings:
        values = dict(
            engine="replay",
            replay_fixture=replay_fixture,
            storage_backend="local",
            storage_root=tmp_path / "store",
            database_url=database_url,
            run_worker=False,
        )
        values.update(overrides)
        # Never read the developer's .env: tests must not reach a real object
        # store (GARAGE_*) or depend on local settings.
        return Settings(_env_file=None, **values)

    return _make


# ---- sample files, generated in memory -------------------------------------

def make_png(width: int = 200, height: int = 100) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (255, 255, 255)).save(buf, "PNG")
    return buf.getvalue()

def make_tiff(pages: int) -> bytes:
    imgs = [Image.new("RGB", (200, 100), (i * 30, 0, 0)) for i in range(pages)]
    buf = io.BytesIO()
    imgs[0].save(buf, "TIFF", save_all=True, append_images=imgs[1:])
    return buf.getvalue()