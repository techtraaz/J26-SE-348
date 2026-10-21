"""Small image helpers shared by services."""

import io

import numpy as np
from PIL import Image

def encode_png(image_bgr: np.ndarray) -> bytes:
    """Lossless PNG bytes from a BGR uint8 array."""
    buf = io.BytesIO()
    Image.fromarray(image_bgr[:, :, ::-1]).save(buf, "PNG")
    return buf.getvalue()