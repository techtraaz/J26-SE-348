"""FastAPI application factory.

Run (from the backend folder):
    uv run fastapi dev app/main.py
Docs UI: http://127.0.0.1:8000/docs
"""

import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import Settings
from app.services.ingestion.models import IngestionError
from app.services.factory import create_engine
from app.services.ocr.paddle import PaddleSettings
from app.services.storage.local import LocalStorage

# Ingestion failure code -> HTTP status. Codes are stable; the frontend can
# branch on them, and `message` is safe to display.
_STATUS_BY_CODE = {
    "empty_file": 400,
    "unsupported_type": 415,
    "too_large": 413,
    "too_many_pages": 422,
    "image_too_large": 422,
    "password_protected": 422,
    "corrupt": 422,
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Heavy objects are built once at startup, never per request.
    settings: Settings = app.state.settings
    app.state.storage = LocalStorage(settings.storage_root)
    app.state.engine = create_engine(
        settings.engine,
        settings=PaddleSettings(),
        fixture=settings.replay_fixture,
        simulate_delay_s=settings.replay_delay_s,
    )
    app.state.engine_lock = threading.Lock()
    yield

def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="Nomos Extraction API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings or Settings()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=app.state.settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(IngestionError)
    async def ingestion_error_handler(request: Request, exc: IngestionError) -> JSONResponse:
        return JSONResponse(
            status_code=_STATUS_BY_CODE.get(exc.code, 422),
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()