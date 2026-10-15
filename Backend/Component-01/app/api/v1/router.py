from fastapi import APIRouter

from app.api.v1 import dev, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(dev.router)