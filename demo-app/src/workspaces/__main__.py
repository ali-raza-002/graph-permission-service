import uvicorn

from workspaces.config import get_settings

settings = get_settings()
uvicorn.run("workspaces.main:app", host=settings.host, port=settings.port, log_config=None)
