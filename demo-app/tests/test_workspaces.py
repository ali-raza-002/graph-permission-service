"""End-to-end: the Workspaces app talking to a real Warden instance over HTTP (in-process
ASGI transport), both backed by Postgres."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config
from asgi_lifespan import LifespanManager
from pydantic import SecretStr
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import create_async_engine

from warden.api.app import create_app as create_warden
from warden.config import Settings as WardenSettings
from warden.container import Container
from warden_sdk import WardenClient
from workspaces import seed_data
from workspaces.app import create_app
from workspaces.config import Settings
from workspaces.db import Database, DocumentRow, FolderRow, OrgRow, TeamRow, UserRow

DATABASE_URL = os.environ.get(
    "WORKSPACES_TEST_DATABASE_URL",
    "postgresql+asyncpg://warden:warden@127.0.0.1:5506/warden_demo_test",
)
ADMIN_KEY = "wdn_test_workspaces-admin-key"
BACKEND = Path(__file__).resolve().parents[2] / "backend"


async def _prepare_database() -> None:
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await conn.execute(text("DROP SCHEMA IF EXISTS workspaces CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    except (OSError, ConnectionError) as exc:
        pytest.skip(f"Postgres is not reachable: {exc}")
    finally:
        await engine.dispose()
    config = Config(str(BACKEND / "alembic.ini"))
    config.attributes["database_url"] = DATABASE_URL
    await asyncio.to_thread(command.upgrade, config, "head")


async def _seed_rows() -> None:
    db = Database(DATABASE_URL)
    await db.create_schema()
    async with db.sessions() as session, session.begin():
        for table in (DocumentRow, FolderRow, TeamRow, OrgRow, UserRow):
            await session.execute(delete(table))
        session.add(OrgRow(id="lumen", name="Lumen Labs"))
        session.add_all(
            UserRow(handle=u.handle, name=u.name, title=u.title, email=f"{u.handle}@lumen.dev")
            for u in seed_data.USERS
        )
        await session.flush()
        for folder in sorted(seed_data.FOLDERS, key=lambda f: f.parent_id is not None):
            session.add(
                FolderRow(
                    id=folder.id,
                    org_id="lumen",
                    parent_id=folder.parent_id,
                    name=folder.name,
                    description=folder.description,
                )
            )
            await session.flush()
        session.add_all(
            DocumentRow(
                id=d.id, folder_id=d.folder_id, title=d.title, body=d.body, created_by=d.owner
            )
            for d in seed_data.DOCUMENTS
        )
    await db.dispose()


@dataclass(frozen=True)
class Stack:
    http: httpx.AsyncClient
    warden: WardenClient


@pytest.fixture(scope="session")
async def stack() -> AsyncIterator[Stack]:
    await _prepare_database()
    warden_settings = WardenSettings(
        _env_file=None,
        env="test",
        database_url=DATABASE_URL,
        bootstrap_admin_key=SecretStr(ADMIN_KEY),
        decision_log="off",
        log_level="WARNING",
    )
    warden_app = create_warden(warden_settings, Container.build(warden_settings))
    async with LifespanManager(warden_app) as warden_manager:
        transport = httpx.ASGITransport(app=warden_manager.app)
        admin = WardenClient("http://warden", ADMIN_KEY, transport=transport)
        store = await admin.create_store("workspaces-e2e")
        client = admin.for_store(store.id)
        await client.write_model(
            files("workspaces").joinpath("authorization.warden").read_text("utf-8")
        )
        await client.write(seed_data.TUPLES)
        await _seed_rows()

        settings = Settings(
            _env_file=None,
            database_url=DATABASE_URL,
            warden_store_id=store.id,
            warden_api_key=SecretStr("unused-the-client-is-injected"),
        )
        workspaces = create_app(settings, warden=client)
        async with (
            LifespanManager(workspaces) as manager,
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=manager.app), base_url="http://workspaces"
            ) as http,
        ):
            yield Stack(http=http, warden=client)
        await admin.aclose()


@pytest.fixture
def app(stack: Stack) -> httpx.AsyncClient:
    return stack.http


async def _as(
    http: httpx.AsyncClient, user: str, method: str, path: str, **kwargs: Any
) -> httpx.Response:
    return await http.request(method, path, headers={"X-Workspaces-User": user}, **kwargs)


async def test_identity_is_required(app: httpx.AsyncClient) -> None:
    assert (await app.get("/api/folders")).status_code == 401
    assert (await _as(app, "mallory", "GET", "/api/folders")).status_code == 401


async def test_folders_follow_team_and_org_relationships(app: httpx.AsyncClient) -> None:
    async def folders(user: str) -> set[str]:
        return {f["id"] for f in (await _as(app, user, "GET", "/api/folders")).json()}

    assert await folders("fatima") == {"partners"}
    assert "leadership" not in await folders("dev")
    assert "leadership" in await folders("chloe")
    assert {"engineering", "rfcs", "incidents", "handbook"} <= await folders("dev")


async def test_blocked_user_is_denied_with_a_decision_id(app: httpx.AsyncClient) -> None:
    denied = await _as(app, "dev", "GET", "/api/documents/credential-leak-review")
    assert denied.status_code == 403
    assert denied.json()["detail"]["decision_id"].startswith("dec_")
    allowed = await _as(app, "anne", "GET", "/api/documents/credential-leak-review")
    assert allowed.status_code == 200

    listing = await _as(app, "dev", "GET", "/api/folders/incidents")
    assert [d["id"] for d in listing.json()["documents"]] == ["pg-failover-review"]


async def test_contractor_can_edit_but_not_reshare(app: httpx.AsyncClient) -> None:
    detail = await _as(app, "fatima", "GET", "/api/documents/partner-sla")
    assert detail.json()["permissions"] == {
        "can_edit": True,
        "can_share": False,
        "can_delete": False,
    }
    share = await _as(
        app,
        "fatima",
        "POST",
        "/api/documents/partner-sla/shares",
        json={"subject": "user:ben", "role": "viewer"},
    )
    assert share.status_code == 403


async def test_create_share_and_delete_document(app: httpx.AsyncClient) -> None:
    created = await _as(
        app,
        "dev",
        "POST",
        "/api/folders/rfcs/documents",
        json={"title": "RFC-014: Check cache", "body": "Cache by revision."},
    )
    assert created.status_code == 201, created.text
    document = created.json()["document"]
    assert created.json()["permissions"]["can_delete"] is True

    path = f"/api/documents/{document['id']}"
    assert (await _as(app, "fatima", "GET", path)).status_code == 403
    shared = await _as(
        app, "dev", "POST", f"{path}/shares", json={"subject": "user:fatima", "role": "viewer"}
    )
    assert {"subject": "user:fatima", "role": "viewer"} in shared.json()["shares"]
    assert "user:fatima" in shared.json()["effective_viewers"]
    assert (await _as(app, "fatima", "GET", path)).status_code == 200

    edit = await _as(app, "fatima", "PATCH", path, json={"title": "Hijacked"})
    assert edit.status_code == 403

    await _as(
        app, "dev", "POST", f"{path}/unshare", json={"subject": "user:fatima", "role": "viewer"}
    )
    assert (await _as(app, "fatima", "GET", path)).status_code == 403

    assert (await _as(app, "anne", "DELETE", path)).status_code == 403
    assert (await _as(app, "dev", "DELETE", path)).status_code == 204
    assert (await _as(app, "dev", "GET", path)).status_code == 403


async def test_invalid_share_subject_is_rejected(app: httpx.AsyncClient) -> None:
    response = await _as(
        app,
        "anne",
        "POST",
        "/api/documents/rfc-012-rebac/shares",
        json={"subject": "admin", "role": "viewer"},
    )
    assert response.status_code == 422


async def _create(app: httpx.AsyncClient, owner: str, title: str) -> str:
    created = await _as(
        app, owner, "POST", "/api/folders/rfcs/documents", json={"title": title, "body": ""}
    )
    assert created.status_code == 201, created.text
    document_id: str = created.json()["document"]["id"]
    return document_id


async def test_only_owners_block_or_revoke(app: httpx.AsyncClient) -> None:
    path = f"/api/documents/{await _create(app, 'dev', 'RFC-015: Quotas')}"
    shared = await _as(
        app, "dev", "POST", f"{path}/shares", json={"subject": "user:anne", "role": "editor"}
    )
    assert shared.json()["can_manage"] is True

    access = await _as(app, "anne", "GET", f"{path}/access")
    assert (access.json()["can_share"], access.json()["can_manage"]) == (True, False)
    viewer = {"subject": "user:ben", "role": "viewer"}
    assert (await _as(app, "anne", "POST", f"{path}/shares", json=viewer)).status_code == 200

    block = {"subject": "user:dev", "role": "blocked"}
    denied = await _as(app, "anne", "POST", f"{path}/shares", json=block)
    assert denied.status_code == 403
    assert denied.json()["detail"]["decision_id"].startswith("dec_")
    assert (await _as(app, "anne", "POST", f"{path}/unshare", json=viewer)).status_code == 403
    assert (await _as(app, "dev", "POST", f"{path}/unshare", json=viewer)).status_code == 200


async def test_access_tolerates_tuples_written_elsewhere(stack: Stack) -> None:
    document_id = await _create(stack.http, "dev", "RFC-016: Console writes")
    await stack.warden.write([f"document:{document_id}#viewer@user:Anne.Smith"])
    access = await _as(stack.http, "dev", "GET", f"/api/documents/{document_id}/access")
    assert access.status_code == 200, access.text
    assert {"subject": "user:Anne.Smith", "role": "viewer"} in access.json()["shares"]


async def test_deleting_a_widely_shared_document_removes_every_tuple(stack: Stack) -> None:
    document_id = await _create(stack.http, "dev", "RFC-017: Everyone")
    viewers = [f"document:{document_id}#viewer@user:guest-{n}" for n in range(260)]
    for start in range(0, len(viewers), 200):
        await stack.warden.write(viewers[start : start + 200])

    access = await _as(stack.http, "dev", "GET", f"/api/documents/{document_id}/access")
    assert len(access.json()["shares"]) == 260, "access follows every page of tuples"

    deleted = await _as(stack.http, "dev", "DELETE", f"/api/documents/{document_id}")
    assert deleted.status_code == 204
    remaining = await stack.warden.read(object_type="document", object_id=document_id)
    assert remaining.items == []
