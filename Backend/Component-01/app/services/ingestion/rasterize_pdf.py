"""Rasterize PDFs to BGR page images at a fixed, recorded DPI.

Born-digital PDFs are rasterized too: one input path for every engine, and
can degrade the same images production uses.
"""

import numpy as np
import pypdfium2 as pdfium

from app.services.ingestion.models import IngestionError, IngestionLimits, PageImage

_POINTS_PER_INCH = 72

def rasterize_pdf(data: bytes, dpi: int, limits: IngestionLimits) -> list[PageImage]:
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        if "password" in str(exc).lower():
            raise IngestionError(
                "password_protected", "The PDF is password-protected."
            ) from exc
        raise IngestionError("corrupt", "The PDF could not be read.") from exc

    try:
        count = len(pdf)
        if count == 0:
            raise IngestionError("corrupt", "The PDF has no pages.")
        if count > limits.max_pages:
            raise IngestionError(
                "too_many_pages",
                f"The PDF has {count} pages; the limit is {limits.max_pages}.",
            )

        scale = dpi / _POINTS_PER_INCH
        pages: list[PageImage] = []
        for index in range(count):
            page = pdf[index]
            try:
                width_pt, height_pt = page.get_size()
                if round(width_pt * scale) * round(height_pt * scale) > limits.max_pixels_per_page:
                    raise IngestionError(
                        "image_too_large",
                        f"Page {index + 1} is too large to rasterize at {dpi} DPI.",
                    )
                # Default render: white background, BGR byte order.
                array = page.render(scale=scale).to_numpy()
                pages.append(
                    PageImage(
                        page_number=index + 1,
                        image=np.ascontiguousarray(array[:, :, :3]),
                        dpi=dpi,
                    )
                )
            finally:
                page.close()
        return pages

    except pdfium.PdfiumError as exc:
        raise IngestionError("corrupt", "The PDF could not be rendered.") from exc
    finally:
        pdf.close()