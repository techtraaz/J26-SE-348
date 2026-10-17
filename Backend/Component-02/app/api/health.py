from fastapi import APIRouter

from app.graph import neo4j_client

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "neo4j": "up" if neo4j_client.ping() else "down"}
