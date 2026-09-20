from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from warden import __version__
from warden.api.deps import ContainerDep

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/readyz", response_model=None)
async def readyz(container: ContainerDep) -> JSONResponse | dict[str, str]:
    try:
        await container.db.ping()
    except Exception as exc:
        return JSONResponse(
            status_code=503, content={"status": "unavailable", "database": type(exc).__name__}
        )
    return {"status": "ready", "database": "ok", "cache": container.settings.cache_backend}
