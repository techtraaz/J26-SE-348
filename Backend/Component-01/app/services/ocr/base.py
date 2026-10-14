"""Interface every recognition engine implements."""

from abc import ABC, abstractmethod

import numpy as np

from app.schemas.extraction import EngineInfo, PageResult


class OCREngine(ABC):
    @abstractmethod
    def info(self) -> EngineInfo:
        """Engine name, version and the exact settings in use."""

    @abstractmethod
    def recognize_page(self, image: np.ndarray, page_number: int = 1) -> PageResult:
        """Recognize one page image (BGR uint8, as returned by cv2)."""