from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health
from app.config import get_settings
from app.graph.neo4j_client import close_driver


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    close_driver()


app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
app.include_router(health.router)
