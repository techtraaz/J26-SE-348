"""Ingestion tests. Every input file is generated in memory with Pillow, so
no binary fixtures are committed."""

import hashlib
import io

import numpy as np
import pytest
from PIL import Image

from app.services.ingestion.detect import detect_kind
from app.services.ingestion.models import FileKind, IngestionError, IngestionLimits
from app.services.ingestion.pipeline import ingest


def _save(img: Image.Image, fmt: str, **kwargs) -> bytes:
    buf = io.BytesIO()
    img.save(buf, fmt, **kwargs)
    return buf.getvalue()


def _red(width: int = 40, height: int = 20) -> Image.Image:
    return Image.new("RGB", (width, height), (255, 0, 0))


def _multipage(fmt: str, pages: int, **kwargs) -> bytes:
    imgs = [Image.new("RGB", (60, 30), (i * 40, 0, 0)) for i in range(pages)]
    return _save(imgs[0], fmt, save_all=True, append_images=imgs[1:], **kwargs)


# ---------- detection ----------


@pytest.mark.parametrize(
    "fmt, kind",
    [
        ("PNG", FileKind.PNG),
        ("JPEG", FileKind.JPEG),
        ("TIFF", FileKind.TIFF),
        ("BMP", FileKind.BMP),
        ("WEBP", FileKind.WEBP),
        ("PDF", FileKind.PDF),
    ],
)
def test_detects_each_supported_kind(fmt, kind):
    assert detect_kind(_save(_red(), fmt)) is kind


def test_detection_ignores_filenames_and_rejects_text():
    with pytest.raises(IngestionError) as err:
        detect_kind(b"BM this is just a text file pretending to be a bitmap")
    assert err.value.code == "unsupported_type"


def test_empty_file_is_rejected():
    with pytest.raises(IngestionError) as err:
        ingest(b"")
    assert err.value.code == "empty_file"


# ---------- raster images ----------


def test_png_decodes_to_bgr_channel_order():
    result = ingest(_save(_red(), "PNG"))

    image = result.pages[0].image
    assert image.shape == (20, 40, 3) and image.dtype == np.uint8
    assert tuple(image[0, 0]) == (0, 0, 255)  # pure red in BGR
    assert result.pages[0].page_number == 1 and result.pages[0].dpi is None


def test_transparent_png_is_composited_on_white():
    rgba = Image.new("RGBA", (10, 10), (0, 0, 0, 0))  # fully transparent
    image = ingest(_save(rgba, "PNG")).pages[0].image

    assert tuple(image[0, 0]) == (255, 255, 255)


def test_exif_orientation_is_applied():
    img = _red(40, 20)
    exif = img.getexif()
    exif[0x0112] = 6  # rotate 90 degrees on display
    image = ingest(_save(img, "JPEG", exif=exif)).pages[0].image

    assert image.shape[:2] == (40, 20)  # width and height swapped


def test_16bit_grayscale_tiff_is_scaled_to_8bit():
    arr = np.array([[0, 65535], [32768, 65535]], dtype=np.uint16)
    image = ingest(_save(Image.fromarray(arr), "TIFF")).pages[0].image

    assert image.dtype == np.uint8
    assert image[0, 0, 0] == 0 and image[0, 1, 0] == 255
    assert 126 <= image[1, 0, 0] <= 129


def test_multipage_tiff_gives_ordered_pages():
    result = ingest(_multipage("TIFF", 3))

    assert result.kind is FileKind.TIFF
    assert [p.page_number for p in result.pages] == [1, 2, 3]
    assert result.pages[2].image[0, 0, 2] == 80  # third page's red channel


def test_sha256_is_of_the_original_bytes():
    data = _save(_red(), "PNG")

    assert ingest(data).sha256 == hashlib.sha256(data).hexdigest()


# ---------- PDF ----------


def test_pdf_pages_are_rasterized_at_the_requested_dpi():
    # Pillow writes 1 image pixel = 1 PDF point, so a 200x100 image is a
    # 200x100 pt page; at 144 DPI (scale 2) that renders to 400x200 px.
    pdf = _save(Image.new("RGB", (200, 100), (255, 0, 0)), "PDF")
    result = ingest(pdf, pdf_dpi=144)

    page = result.pages[0]
    assert abs(page.image.shape[1] - 400) <= 1 and abs(page.image.shape[0] - 200) <= 1
    assert page.dpi == 144
    b, g, r = (int(v) for v in page.image[100, 200])
    assert b < 10 and g < 10 and r > 245  # red in BGR order (Pillow embeds JPEG, so not exact)


def test_multipage_pdf_gives_ordered_pages():
    result = ingest(_multipage("PDF", 3), pdf_dpi=72)

    assert result.kind is FileKind.PDF
    assert [p.page_number for p in result.pages] == [1, 2, 3]


# ---------- limits and failures ----------


def test_file_size_limit():
    with pytest.raises(IngestionError) as err:
        ingest(_save(_red(), "PNG"), limits=IngestionLimits(max_file_bytes=50))
    assert err.value.code == "too_large"


def test_page_count_limit_for_tiff_and_pdf():
    for fmt in ("TIFF", "PDF"):
        with pytest.raises(IngestionError) as err:
            ingest(_multipage(fmt, 3), limits=IngestionLimits(max_pages=2))
        assert err.value.code == "too_many_pages"


def test_pixel_limit_for_images_and_pdf_pages():
    limits = IngestionLimits(max_pixels_per_page=100)
    for data in (_save(_red(40, 20), "PNG"), _save(_red(40, 20), "PDF")):
        with pytest.raises(IngestionError) as err:
            ingest(data, limits=limits)
        assert err.value.code == "image_too_large"


def test_corrupt_files_are_reported_not_crashed():
    truncated_png = _save(_red(), "PNG")[:30]
    garbage_pdf = b"%PDF-1.7\nthis is not a real pdf body"

    for data in (truncated_png, garbage_pdf):
        with pytest.raises(IngestionError) as err:
            ingest(data)
        assert err.value.code == "corrupt"


def test_invalid_dpi_is_a_programming_error():
    with pytest.raises(ValueError):
        ingest(_save(_red(), "PNG"), pdf_dpi=5)