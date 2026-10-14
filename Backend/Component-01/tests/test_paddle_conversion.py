"""Tests the raw PaddleOCR result -> schema conversion without loading models.

The fake result mimics the real structure seen in the smoke run: parallel
arrays, int16 numpy boxes/polygons, and a dict-like container.
"""

import numpy as np
import pytest

from app.schemas.extraction import EngineInfo, ExtractionResult, PageResult
from app.services.ocr.paddle import lines_from_result


def _fake_result() -> dict:
    return {
        "rec_texts": ["12/10/36", "09:51"],
        "rec_scores": [0.999794065952301, 0.9107236862182617],
        "rec_boxes": np.array([[44, 15, 120, 29], [131, 18, 190, 32]], dtype=np.int16),
        "rec_polys": [
            np.array([[44, 15], [120, 15], [120, 29], [44, 29]], dtype=np.int16),
            np.array([[131, 18], [190, 18], [190, 32], [131, 32]], dtype=np.int16),
        ],
    }


def test_conversion_values_and_plain_types():
    lines = lines_from_result(_fake_result())

    assert len(lines) == 2
    assert lines[0].text == "12/10/36"
    assert lines[0].confidence == pytest.approx(0.9997940659)
    assert lines[0].box == (44, 15, 120, 29)
    assert lines[1].polygon[2] == (190, 32)

    # Must be built-in Python types, not numpy scalars (JSON-serializable).
    assert type(lines[0].confidence) is float
    assert all(type(v) is int for v in lines[0].box)


def test_full_result_serializes_to_json():
    page = PageResult(
        page_number=1,
        width=754,
        height=1000,
        lines=lines_from_result(_fake_result()),
        elapsed_ms=12.5,
    )
    result = ExtractionResult(
        engine=EngineInfo(name="paddleocr", version="x", settings={"lang": "en"}),
        pages=[page],
    )
    assert "12/10/36" in result.model_dump_json()


def test_blank_page_gives_no_lines():
    empty = {
        "rec_texts": [],
        "rec_scores": [],
        "rec_boxes": np.empty((0, 4), dtype=np.int16),
        "rec_polys": [],
    }
    assert lines_from_result(empty) == []


def test_mismatched_array_lengths_raise():
    broken = _fake_result()
    broken["rec_scores"] = [0.99]
    with pytest.raises(ValueError):
        lines_from_result(broken)