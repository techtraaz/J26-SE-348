from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, kg, ontology, policies, query
from app.config import get_settings
from app.graph.neo4j_client import close_driver


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    close_driver()


settings = get_settings()
app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(CORSMiddleware,
                   allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(health.router)
app.include_router(ontology.router)
app.include_router(kg.router)
app.include_router(query.router)
app.include_router(policies.router)
