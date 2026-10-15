"""Decode raster files (PNG, JPEG, TIFF incl. multi-page, BMP, WebP) into
BGR uint8 page images, the one format every engine receives."""

import io

import numpy as np
from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

from app.services.ingestion.models import FileKind, IngestionError, IngestionLimits, PageImage

def _to_bgr(frame: Image.Image) -> np.ndarray:
    # Apply EXIF orientation so phone photos are upright. The image we store
    # and show is the image that recognize, so geometry stays consistent.
    frame = ImageOps.exif_transpose(frame)

    if frame.mode.startswith("I;16"):
        # 16-bit grayscale scans: scale 0..65535 down to 0..255.
        gray = np.clip(np.asarray(frame, dtype=np.float64) / 257.0, 0, 255).astype(np.uint8)
        return np.stack([gray, gray, gray], axis=-1)

    has_alpha = frame.mode in ("RGBA", "LA", "PA") or (
        frame.mode == "P" and "transparency" in frame.info
    )
    if has_alpha:
        # Composite onto white; naive conversion would turn transparency black.
        rgba = frame.convert("RGBA")
        white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        frame = Image.alpha_composite(white, rgba).convert("RGB")
    else:
        frame = frame.convert("RGB")

    return np.asarray(frame)[:, :, ::-1].copy()  # RGB -> BGR, contiguous

def load_image_pages(data: bytes, kind: FileKind, limits: IngestionLimits) -> list[PageImage]:
    try:
        with Image.open(io.BytesIO(data)) as img:
            # Only TIFF is treated as multi-page; other formats use frame 1.
            is_multipage = kind is FileKind.TIFF
            n_frames = getattr(img, "n_frames", 1) if is_multipage else 1
            if n_frames > limits.max_pages:
                raise IngestionError(
                    "too_many_pages",
                    f"The file has {n_frames} pages; the limit is {limits.max_pages}.",
                )

            frames = ImageSequence.Iterator(img) if is_multipage else [img]
            pages: list[PageImage] = []
            for number, frame in enumerate(frames, start=1):
                if frame.width * frame.height > limits.max_pixels_per_page:
                    raise IngestionError(
                        "image_too_large",
                        f"Page {number} is {frame.width}x{frame.height}px, "
                        f"over the {limits.max_pixels_per_page // 1_000_000} megapixel limit.",
                    )
                pages.append(PageImage(page_number=number, image=_to_bgr(frame), dpi=None))
            return pages

    except IngestionError:
        raise
    except Image.DecompressionBombError as exc:
        raise IngestionError("image_too_large", "The image is too large to process.") from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError) as exc:
        raise IngestionError("corrupt", "The file could not be read as an image.") from exc