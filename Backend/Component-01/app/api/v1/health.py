from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_engine
from app.services.ocr.base import OCREngine

router = APIRouter(tags=["health"])

@router.get("/health")
def health(engine: Annotated[OCREngine, Depends(get_engine)]) -> dict:
    info = engine.info()
    return {"status": "ok", "engine": info.name, "engine_version": info.version}