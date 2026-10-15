"""Dependencies that hand shared objects (built once at startup) to routes."""

from fastapi import Request

from app.core.config import Settings
from app.services.ocr.base import OCREngine
from app.services.storage.base import Storage

def get_settings(request: Request) -> Settings:
    return request.app.state.settings

def get_engine(request: Request) -> OCREngine:
    return request.app.state.engine

def get_storage(request: Request) -> Storage:
    return request.app.state.storage