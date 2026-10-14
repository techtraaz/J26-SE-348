"""Interface every recognition engine implements (Paddle now, VLM in Phase 2)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from app.schemas.extraction import EngineInfo, PageResult


@dataclass
class PageRecognition:
    """What an engine returns for one page.

    `page` holds the schema data (JSON-safe). `ocr_image` is the exact image
    the box coordinates refer to: the engine's own preprocessed image
    (rotated / unwarped) when it has one, otherwise the input image.
    It is a numpy array, so it stays out of the schema and is stored by the
    storage layer as a file (design decision D3).
    """

    page: PageResult
    ocr_image: np.ndarray


class OCREngine(ABC):
    @abstractmethod
    def info(self) -> EngineInfo:
        """Engine name, version and the exact settings in use."""

    @abstractmethod
    def recognize_page(self, image: np.ndarray, page_number: int = 1) -> PageRecognition:
        """Recognize one page image (BGR uint8, as returned by cv2)."""