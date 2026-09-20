from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.helpers import WORKSPACE_MODEL
from warden.api.app import create_app
from warden.config import Settings
from warden.container import Container

TEST_DATABASE_URL = os.environ.get(
    "WARDEN_TEST_DATABASE_URL", "postgresql+asyncpg://warden:warden@127.0.0.1:5506/warden_test"
)
ADMIN_KEY = "wdn_test_admin-key-for-integration-tests"
BACKEND_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.integration

type ClientFactory = Callable[..., Awaitable[httpx.AsyncClient]]


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "env": "test",
        "database_url": TEST_DATABASE_URL,
        "decision_log": "sync",
        "bootstrap_admin_key": ADMIN_KEY,
        "cache_backend": "memory",
        "db_pool_size": 5,
        "log_level": "WARNING",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture(scope="session")
async def database() -> str:
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    except (OSError, ConnectionError) as exc:
        pytest.skip(f"Postgres is not reachable at {TEST_DATABASE_URL}: {exc}")
    finally:
        await engine.dispose()
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["database_url"] = TEST_DATABASE_URL
    await asyncio.to_thread(command.upgrade, config, "head")
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
async def client_factory(database: str) -> AsyncIterator[ClientFactory]:
    managers: list[LifespanManager] = []
    clients: list[httpx.AsyncClient] = []

    async def make(api_key: str | None = ADMIN_KEY, **overrides: Any) -> httpx.AsyncClient:
        settings = _settings(**overrides)
        app = create_app(settings, Container.build(settings))
        manager = LifespanManager(app)
        await manager.__aenter__()
        managers.append(manager)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=manager.app),
            base_url="http://warden",
            headers=headers,
        )
        clients.append(client)
        return client

    yield make
    for client in clients:
        await client.aclose()
    for manager in reversed(managers):
        await manager.__aexit__(None, None, None)


@pytest.fixture(scope="session")
async def client(client_factory: ClientFactory) -> httpx.AsyncClient:
    return await client_factory()


@pytest.fixture
async def store(client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.post("/v1/stores", json={"name": "integration"})
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    model = await client.post(f"/v1/stores/{created['id']}/models", json={"dsl": WORKSPACE_MODEL})
    assert model.status_code == 201, model.text
    created["model_id"] = model.json()["id"]
    return created


def tk(obj: str, relation: str, user: str) -> dict[str, str]:
    return {"object": obj, "relation": relation, "user": user}
