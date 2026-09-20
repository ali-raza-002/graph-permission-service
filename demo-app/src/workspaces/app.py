from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from warden_sdk import WardenClient, WardenError
from workspaces.api import router
from workspaces.config import Settings, get_settings
from workspaces.db import Database
from workspaces.repository import WorkspaceRepository
from workspaces.service import ForbiddenError, NotFoundError, WorkspaceService

log = structlog.get_logger("workspaces")


def create_app(settings: Settings | None = None, warden: WardenClient | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level.upper(), format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(settings.database_url)
        await db.create_schema()
        client = warden or WardenClient(
            settings.warden_url,
            settings.warden_api_key.get_secret_value(),
            store_id=settings.warden_store_id,
        )
        repository = WorkspaceRepository(db)
        app.state.warden = client
        app.state.repository = repository
        app.state.service = WorkspaceService(repository, client)
        log.info("workspaces_started", store=settings.warden_store_id, warden=settings.warden_url)
        try:
            yield
        finally:
            if warden is None:
                await client.aclose()
            await db.dispose()

    app = FastAPI(
        title="Workspaces",
        description="Demo SaaS whose every permission decision is delegated to Warden.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Workspaces-User"],
    )

    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ForbiddenError)
    async def _forbidden(_: Request, exc: ForbiddenError) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={
                "detail": {"code": "forbidden", "message": str(exc), "decision_id": exc.decision_id}
            },
        )

    @app.exception_handler(WardenError)
    async def _warden(_: Request, exc: WardenError) -> JSONResponse:
        log.warning("warden_error", code=exc.code, status=exc.status, message=exc.message)
        status_code = 422 if exc.status in {400, 409, 422} else 503
        return JSONResponse(
            status_code=status_code, content={"detail": exc.message, "code": exc.code}
        )

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(router)
    return app
