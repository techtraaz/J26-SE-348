"""One error shape for the whole API: {"error": {"code": ..., "message": ...}}.

`code` is stable and machine-readable (the frontend branches on it);
`message` is safe to show to a user.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.services.ingestion.models import IngestionError

# Ingestion failure code -> HTTP status (used when an upload is rejected
# immediately; failures found later by the worker are stored on the document).
_STATUS_BY_INGESTION_CODE = {
    "empty_file": 400,
    "unsupported_type": 415,
    "too_large": 413,
    "too_many_pages": 422,
    "image_too_large": 422,
    "password_protected": 422,
    "corrupt": 422,
}

class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message

def _body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}

def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=_body(exc.code, exc.message))

    @app.exception_handler(IngestionError)
    async def _ingestion_error(request: Request, exc: IngestionError) -> JSONResponse:
        status = _STATUS_BY_INGESTION_CODE.get(exc.code, 422)
        return JSONResponse(status_code=status, content=_body(exc.code, exc.message))