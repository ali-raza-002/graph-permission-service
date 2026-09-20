from __future__ import annotations

import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from warden import __version__
from warden.api.errors import install_error_handlers
from warden.api.routes import decisions, health, keys, models, queries, stores, tuples
from warden.config import Settings, get_settings
from warden.container import Container
from warden.logging import configure_logging, get_logger

log = get_logger("warden.http")

_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


def _request_id(raw: str | None) -> str:
    return raw if raw is not None and _REQUEST_ID.fullmatch(raw) else uuid.uuid4().hex


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container or Container.build(settings)
        await app.state.container.start()
        log.info("warden_started", env=settings.env, cache=settings.cache_backend)
        try:
            yield
        finally:
            await app.state.container.close()

    app = FastAPI(
        title="Warden",
        version=__version__,
        description="Relationship-based authorization inspired by Google Zanzibar.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = _request_id(request.headers.get("x-request-id"))
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers["X-Request-ID"] = request_id
        if request.url.path not in {"/healthz", "/readyz"}:
            log.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                request_id=request_id,
            )
        return response

    install_error_handlers(app)
    for module in (health, stores, models, tuples, queries, decisions, keys):
        app.include_router(module.router)
    return app
