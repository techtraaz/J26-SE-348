from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_engine
from app.services.ocr.base import OCREngine

router = APIRouter(tags=["health"])

@router.get("/health")
def health(request: Request, engine: Annotated[OCREngine, Depends(get_engine)]) -> dict:
    info = engine.info()
    worker = getattr(request.app.state, "worker", None)
    return {
        "status": "ok",
        "engine": info.name,
        "engine_version": info.version,
        "worker_running": bool(worker and worker.is_alive()),
    }