from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from warden.core.errors import WardenError
from warden.dsl.issues import ModelCompileError
from warden.logging import get_logger

log = get_logger(__name__)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[dict[str, Any]] = []


class ErrorResponse(BaseModel):
    error: ErrorBody


def _respond(status: int, code: str, message: str, details: list[dict[str, Any]]) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details))
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"), headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(WardenError)
    async def _warden(_: Request, exc: WardenError) -> JSONResponse:
        return _respond(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(ModelCompileError)
    async def _model(_: Request, exc: ModelCompileError) -> JSONResponse:
        return _respond(
            422,
            "invalid_model",
            "the authorization model has errors",
            [issue.model_dump() for issue in exc.issues],
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"location": ".".join(str(p) for p in err.get("loc", ())), "message": err.get("msg")}
            for err in exc.errors()
        ]
        return _respond(422, "validation_failed", "request validation failed", details)

    @app.exception_handler(PoolTimeoutError)
    async def _pool(request: Request, exc: PoolTimeoutError) -> JSONResponse:
        log.warning("db_pool_exhausted", path=request.url.path)
        return _respond(503, "unavailable", "the service is busy, retry shortly", [])

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", path=request.url.path, error=type(exc).__name__)
        return _respond(500, "internal", "an unexpected error occurred", [])
