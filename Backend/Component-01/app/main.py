"""FastAPI application factory.

Run (from the backend folder):
    uv run fastapi dev app/main.py
Docs UI: http://127.0.0.1:8000/docs
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.errors import register_error_handlers
from app.api.v1.router import api_router
from app.core.config import Settings
from app.db.session import create_db_engine, create_session_factory
from app.jobs.worker import JobWorker
from app.services.factory import create_engine
from app.services.ocr.paddle import PaddleSettings
from app.services.storage.local import LocalStorage

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Heavy objects are built once at startup, never per request.
    settings: Settings = app.state.settings

    db_engine = create_db_engine(settings.database_url)
    with db_engine.connect() as connection:  # fail fast if the database is unreachable
        connection.execute(text("SELECT 1"))
    app.state.db_engine = db_engine
    app.state.session_factory = create_session_factory(db_engine)

    app.state.storage = LocalStorage(settings.storage_root)
    app.state.engine = create_engine(
        settings.engine,
        settings=PaddleSettings(),
        fixture=settings.replay_fixture,
        simulate_delay_s=settings.replay_delay_s,
    )

    worker = JobWorker(
        app.state.session_factory, app.state.storage, app.state.engine, settings
    )
    app.state.worker = worker
    if settings.run_worker:
        recovered = worker.recover_interrupted()
        if recovered:
            logger.warning("Re-queued %d interrupted extraction run(s)", recovered)
        worker.start()

    yield

    worker.stop()
    db_engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="AuditMind-LK Extraction API", version="0.2.0", lifespan=lifespan)
    app.state.settings = settings or Settings()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=app.state.settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Location"],
    )
    register_error_handlers(app)
    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()