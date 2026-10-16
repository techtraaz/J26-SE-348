"""API tests through FastAPI's TestClient with the replay engine and a temp
storage folder (the real lifespan runs, so startup wiring is covered)."""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import Settings
from app.main import create_app
from app.schemas.extraction import EngineInfo, ExtractionResult, OCRLine, PageResult

def _fixture_json() -> str:
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
    return result.model_dump_json()

def _client(tmp_path, **overrides) -> TestClient:
    fixture = tmp_path / "fixture.json"
    fixture.write_text(_fixture_json(), encoding="utf-8")
    settings = Settings(
        engine="replay",
        replay_fixture=fixture,
        storage_root=tmp_path / "store",
        **overrides,
    )
    return TestClient(create_app(settings))

def _png(width=200, height=100) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (255, 255, 255)).save(buf, "PNG")
    return buf.getvalue()

def _tiff(pages: int) -> bytes:
    imgs = [Image.new("RGB", (200, 100), (i * 30, 0, 0)) for i in range(pages)]
    buf = io.BytesIO()
    imgs[0].save(buf, "TIFF", save_all=True, append_images=imgs[1:])
    return buf.getvalue()

def _upload(client, data: bytes, name="scan.png"):
    return client.post("/api/v1/dev/extract", files={"file": (name, data)})

@pytest.fixture
def client(tmp_path):
    with _client(tmp_path) as c:
        yield c

def test_health_reports_the_engine(client):
    body = client.get("/api/v1/health").json()

    assert body["status"] == "ok" and body["engine"] == "replay"

def test_extract_png_returns_regions_and_a_fetchable_image(client):
    response = _upload(client, _png())

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "png" and len(body["document_id"]) == 32
    page = body["pages"][0]
    assert page["lines"][0]["text"] == "TOTAL 42.00"
    assert page["lines"][0]["confidence"] == 0.9731  # raw score untouched
    assert (page["width"], page["height"]) == (200, 100)

    image = client.get(page["image_url"])
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(image.content)).size == (200, 100)

def test_extract_multipage_tiff(client):
    body = _upload(client, _tiff(3), "scan.tif").json()

    assert [p["page_number"] for p in body["pages"]] == [1, 2, 3]

def test_original_variant_is_served(client):
    body = _upload(client, _png()).json()

    response = client.get(body["pages"][0]["image_url"] + "?variant=original")
    assert response.status_code == 200

def test_unsupported_file_gets_a_structured_415(client):
    response = _upload(client, b"just some text", "notes.txt")

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_type"

def test_empty_file_gets_400(client):
    response = _upload(client, b"", "empty.png")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "empty_file"

def test_oversized_upload_gets_413(tmp_path):
    with _client(tmp_path, max_file_bytes=100) as c:
        response = _upload(c, _png())

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "too_large"

def test_too_many_pages_gets_422(tmp_path):
    with _client(tmp_path, max_pages=2) as c:
        response = _upload(c, _tiff(3), "scan.tif")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "too_many_pages"

def test_unknown_document_or_page_is_404(client):
    body = _upload(client, _png()).json()

    assert client.get(f"/api/v1/dev/documents/{'0' * 32}/pages/1/image").status_code == 404
    assert client.get(f"/api/v1/dev/documents/{body['document_id']}/pages/9/image").status_code == 404

def test_malformed_document_id_is_rejected_before_touching_storage(client):
    response = client.get("/api/v1/dev/documents/..%2F..%2Fsecrets/pages/1/image")

    assert response.status_code in (404, 422)

def test_uploaded_original_and_result_are_stored(tmp_path):
    with _client(tmp_path) as c:
        doc = _upload(c, _png()).json()["document_id"]

    base = tmp_path / "store" / "documents" / doc
    assert (base / "original.png").is_file()
    assert (base / "result.json").is_file()
    assert (base / "pages" / "1.original.png").is_file()
    assert not (base / "pages" / "1.ocr.png").exists()  # replay never changes the image