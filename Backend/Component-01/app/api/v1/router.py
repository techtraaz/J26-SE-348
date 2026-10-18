from fastapi import APIRouter

from app.api.v1 import documents, folders, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(folders.router)
api_router.include_router(documents.router)