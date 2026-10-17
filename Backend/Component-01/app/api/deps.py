"""Dependencies that hand shared objects (built once at startup) to routes."""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.ocr.base import OCREngine
from app.services.storage.base import Storage

def get_settings(request: Request) -> Settings:
    return request.app.state.settings

def get_engine(request: Request) -> OCREngine:
    return request.app.state.engine

def get_storage(request: Request) -> Storage:
    return request.app.state.storage

def get_db(request: Request) -> Iterator[Session]:
    """One session per request. Handlers commit explicitly, so a response is
    never sent before its data is committed; this only guarantees cleanup."""
    session = request.app.state.session_factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()