from __future__ import annotations

import uvicorn

from warden.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "warden.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.env == "development",
        log_config=None,
    )
