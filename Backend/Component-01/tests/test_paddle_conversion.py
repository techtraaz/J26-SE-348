"""Tests the raw PaddleOCR result -> schema conversion without loading models.

The fake result mimics the real structure seen in the smoke run: parallel
arrays, int16 numpy boxes/polygons, and a dict-like container.
"""

import numpy as np
import pytest

from app.schemas.extraction import EngineInfo, ExtractionResult, PageResult
from app.services.ocr.paddle import (
    PaddleSettings,
    build_paddle_kwargs,
    cpu_flags,
    lines_from_result,
    ocr_image_from_result,
)


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


def test_ocr_image_prefers_preprocessed_output():
    fallback = np.zeros((10, 20, 3), dtype=np.uint8)
    processed = np.ones((12, 18, 3), dtype=np.uint8)
    res = {"doc_preprocessor_res": {"output_img": processed}}

    out = ocr_image_from_result(res, fallback)

    assert out.shape == (12, 18, 3)  # preprocessed size, not the input size


def test_ocr_image_falls_back_to_input_when_no_preprocessing():
    fallback = np.zeros((10, 20, 3), dtype=np.uint8)

    assert ocr_image_from_result({}, fallback) is fallback
    assert ocr_image_from_result({"doc_preprocessor_res": {}}, fallback) is fallback


def test_default_kwargs():
    kwargs = build_paddle_kwargs(PaddleSettings())

    assert kwargs["enable_mkldnn"] is False
    assert kwargs["use_doc_unwarping"] is False
    assert "engine" not in kwargs and "engine_config" not in kwargs
    assert "text_detection_model_name" not in kwargs  # None -> not passed


def test_model_names_are_passed_only_when_set():
    kwargs = build_paddle_kwargs(
        PaddleSettings(text_detection_model_name="det-x", text_recognition_model_name="rec-y")
    )

    assert kwargs["text_detection_model_name"] == "det-x"
    assert kwargs["text_recognition_model_name"] == "rec-y"


def test_cpu_flags_follow_mkldnn_setting():
    assert cpu_flags(PaddleSettings())["FLAGS_use_mkldnn"] == "0"
    assert cpu_flags(PaddleSettings(enable_mkldnn=True))["FLAGS_use_mkldnn"] == "1"