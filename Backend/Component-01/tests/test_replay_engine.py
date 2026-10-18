"""Replay engine + factory tests. Uses a small synthetic fixture written to a
temp file, so the suite does not depend on any real OCR output."""

import numpy as np
import pytest

from app.schemas.extraction import EngineInfo, ExtractionResult, OCRLine, PageResult
from app.services.factory import create_engine
from app.services.replay import ReplayEngine


def _fixture_result(pages: int = 1) -> ExtractionResult:
    line = OCRLine(
        text="TOTAL 42.00",
        confidence=0.9731,
        box=(10, 20, 110, 40),
        polygon=[(10, 20), (110, 20), (110, 40), (10, 40)],
    )
    page = PageResult(page_number=1, width=200, height=100, lines=[line], elapsed_ms=51000.0)
    return ExtractionResult(
        engine=EngineInfo(name="paddleocr", version="3.7.0", settings={"lang": "en"}),
        pages=[page] * pages,
    )


@pytest.fixture
def fixture_path(tmp_path):
    path = tmp_path / "fixture.json"
    path.write_text(_fixture_result().model_dump_json(), encoding="utf-8")
    return path


def _image(width: int, height: int) -> np.ndarray:
    return np.zeros((height, width, 3), dtype=np.uint8)


def test_same_size_input_returns_fixture_unchanged(fixture_path):
    rec = ReplayEngine(fixture_path).recognize_page(_image(200, 100), page_number=3)

    assert rec.page.page_number == 3
    assert (rec.page.width, rec.page.height) == (200, 100)
    assert rec.page.lines[0].box == (10, 20, 110, 40)
    assert rec.page.lines[0].confidence == 0.9731  # raw score untouched


def test_different_size_input_scales_coordinates(fixture_path):
    rec = ReplayEngine(fixture_path).recognize_page(_image(400, 300))

    line = rec.page.lines[0]
    assert (rec.page.width, rec.page.height) == (400, 300)
    assert line.box == (20, 60, 220, 120)  # x doubled, y tripled
    assert line.polygon[2] == (220, 120)


def test_ocr_image_is_the_input_image(fixture_path):
    image = _image(200, 100)

    assert ReplayEngine(fixture_path).recognize_page(image).ocr_image is image


def test_info_marks_results_as_replayed(fixture_path):
    info = ReplayEngine(fixture_path).info()

    assert info.name == "replay"
    assert info.settings["replayed_from"]["name"] == "paddleocr"
    assert info.settings["replayed_from"]["version"] == "3.7.0"


def test_elapsed_is_measured_not_copied_from_fixture(fixture_path):
    rec = ReplayEngine(fixture_path).recognize_page(_image(200, 100))

    assert rec.page.elapsed_ms < 1000  # fixture says 51000


def test_simulated_delay_is_reflected_in_elapsed(fixture_path):
    rec = ReplayEngine(fixture_path, simulate_delay_s=0.05).recognize_page(_image(200, 100))

    assert rec.page.elapsed_ms >= 45


def test_fixture_without_pages_is_rejected(tmp_path):
    path = tmp_path / "empty.json"
    empty = ExtractionResult(
        engine=EngineInfo(name="x", version="1", settings={}), pages=[]
    )
    path.write_text(empty.model_dump_json(), encoding="utf-8")

    with pytest.raises(ValueError):
        ReplayEngine(path)


def test_factory_builds_replay_engine(fixture_path):
    engine = create_engine("replay", fixture=fixture_path)

    assert isinstance(engine, ReplayEngine)


def test_factory_rejects_bad_requests():
    with pytest.raises(ValueError):
        create_engine("replay")  # missing fixture
    with pytest.raises(ValueError):
        create_engine("nope")