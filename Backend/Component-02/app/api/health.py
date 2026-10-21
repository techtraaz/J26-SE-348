from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter

from app.construction import llm
from app.graph import neo4j_client
from app.storage import objects

router = APIRouter(tags=["health"])


def _neo4j() -> tuple[str, str | None]:
    return ("up", None) if neo4j_client.ping() else ("down", "cannot connect to NEO4J_URI")


def _storage() -> tuple[str, str | None]:
    try:
        store = objects.get_store()
        store.ping()
    except objects.StorageNotConfigured:
        return "not configured", "set GARAGE_ENDPOINT, GARAGE_ACCESS_KEY and GARAGE_SECRET_KEY"
    except objects.StorageError as exc:
        return "down", str(exc)
    return "up", f"bucket {store.bucket}"


# the service answers even when a dependency is down; each one is reported on its own
@router.get("/health")
def health() -> dict:
    checks = {"neo4j": _neo4j, "llm": llm.ping, "storage": _storage}
    with ThreadPoolExecutor(max_workers=len(checks)) as pool:
        results = {name: pool.submit(fn) for name, fn in checks.items()}
        results = {name: f.result() for name, f in results.items()}
    return {"status": "ok", **{name: state for name, (state, _) in results.items()},
            "details": {name: reason for name, (_, reason) in results.items() if reason}}
