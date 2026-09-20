"""Provision demo data for Warden and the Workspaces app.

Creates two stores (the Workspaces demo and a Git hosting model), writes their models
and tuples in several revisions, provisions the demo app's and the console's API keys,
fills the demo app's own schema, and replays a day of synthetic checks so the console
has history.

Idempotent by default: if the demo store already exists nothing is changed. Pass
--reset to drop the demo stores and rebuild them.

    python scripts/seed.py [--reset]
"""

from __future__ import annotations

import argparse
import asyncio
import random
from importlib.resources import files
from pathlib import Path

from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import delete, select, text

from warden.auth.keys import Principal, Scope
from warden.config import Settings
from warden.container import Container
from warden.core.refs import RelationTuple
from warden.db.tables import ApiKeyRow, StoreRow
from warden.model.repository import StoreRepository
from warden.queries.schemas import CheckRequest, ListObjectsRequest
from warden.tuples.schemas import TupleKey, WriteCommand
from workspaces import seed_data
from workspaces.config import Settings as WorkspacesSettings
from workspaces.db import Database, DocumentRow, FolderRow, OrgRow, TeamRow, UserRow

ROOT = Path(__file__).resolve().parents[1]
WORKSPACES_STORE = "st_workspaces_demo"
GIT_STORE = "st_git_hosting_demo"
# Everything except key management: the console can run the playground and edit models,
# tuples and stores, but a leaked console key cannot mint new keys.
CONSOLE_SCOPES = [s for s in Scope if s is not Scope.KEYS_ADMIN]


class SeedSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WARDEN_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    console_api_key: SecretStr | None = None


GIT_MODEL = """model
  schema 1.1

type user

type organization
  relations
    define owner: [user]
    define member: [user] or owner
    define repo_admin: [user, organization#member]
    define repo_reader: [user, organization#member]

type team
  relations
    define member: [user, team#member]

type repo
  relations
    define organization: [organization]
    define admin: [user, team#member] or repo_admin from organization or owner from organization
    define maintainer: [user, team#member] or admin
    define writer: [user, team#member] or maintainer
    define triager: [user, team#member] or writer
    define reader: [user, user:*, team#member] or triager or repo_reader from organization
"""

GIT_TUPLES = [
    "organization:octo#owner@user:mona",
    *(f"organization:octo#member@user:{u}" for u in ("hubot", "lin", "sam", "priya")),
    "organization:octo#repo_reader@organization:octo#member",
    "team:infra#member@user:lin",
    "team:infra#member@user:sam",
    "team:maintainers#member@team:infra#member",
    "team:maintainers#member@user:priya",
    *(f"repo:{r}#organization@organization:octo" for r in ("warden", "console", "docs")),
    "repo:warden#maintainer@team:maintainers#member",
    "repo:warden#writer@user:hubot",
    "repo:console#admin@user:priya",
    "repo:console#triager@user:guest",
    "repo:docs#reader@user:*",
]


def _keys(raw: list[str]) -> list[TupleKey]:
    return [TupleKey.from_tuple(RelationTuple.parse(t)) for t in raw]


def _chunks[T](items: list[T], size: int) -> list[list[T]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


async def _reset_store(container: Container, store_id: str, name: str) -> None:
    async with container.db.transaction() as session:
        await session.execute(delete(StoreRow).where(StoreRow.id == store_id))
    await StoreRepository(container.db).create(name, store_id=store_id)


async def _write_in_revisions(container: Container, store_id: str, tuples: list[str]) -> int:
    revision = 0
    for chunk in _chunks(_keys(tuples), 12):
        result = await container.tuples.write(store_id, WriteCommand(writes=chunk))
        revision = result.revision
    return revision


async def _store_exists(container: Container, store_id: str) -> bool:
    async with container.db.session() as session:
        return await session.get(StoreRow, store_id) is not None


async def provision_console_key(container: Container, raw: str) -> None:
    prefix = raw.split("_", 2)[1] if raw.count("_") >= 2 else ""
    async with container.db.transaction() as session:
        existing = await session.scalar(select(ApiKeyRow.id).where(ApiKeyRow.prefix == prefix))
        if existing is not None:
            await session.execute(delete(ApiKeyRow).where(ApiKeyRow.id == existing))
    await container.keys.create(name="console", scopes=CONSOLE_SCOPES, store_id=None, preshared=raw)
    print("  console key provisioned (all scopes except keys:admin)")


async def seed_warden(container: Container, demo_key: str) -> None:
    await _reset_store(container, WORKSPACES_STORE, "Lumen Workspaces")
    model_source = files("workspaces").joinpath("authorization.warden").read_text("utf-8")
    # Version 1 predates the contractor rule, so the console shows a real model history.
    first_draft = model_source.replace(
        "    // External collaborators may edit, but only org members can reshare.\n"
        "    define can_share: owner or (can_edit and member from org)\n",
        "    define can_share: owner or can_edit\n",
    )
    assert first_draft != model_source
    await container.models.write(WORKSPACES_STORE, first_draft)
    await container.models.write(WORKSPACES_STORE, model_source)
    revision = await _write_in_revisions(container, WORKSPACES_STORE, seed_data.TUPLES)
    await container.keys.create(
        name="workspaces-demo-app",
        scopes=[Scope.CHECK, Scope.TUPLES_READ, Scope.TUPLES_WRITE, Scope.MODELS_READ],
        store_id=WORKSPACES_STORE,
        preshared=demo_key,
    )
    print(f"  {WORKSPACES_STORE}: {len(seed_data.TUPLES)} tuples, revision {revision}")

    await _reset_store(container, GIT_STORE, "Git hosting")
    await container.models.write(GIT_STORE, GIT_MODEL)
    revision = await _write_in_revisions(container, GIT_STORE, GIT_TUPLES)
    print(f"  {GIT_STORE}: {len(GIT_TUPLES)} tuples, revision {revision}")


async def seed_workspaces(url: str) -> None:
    db = Database(url)
    await db.create_schema()
    async with db.sessions() as session, session.begin():
        for table in (DocumentRow, FolderRow, TeamRow, OrgRow, UserRow):
            await session.execute(delete(table))
        session.add(OrgRow(id=seed_data.ORG[0], name=seed_data.ORG[1]))
        session.add_all(
            UserRow(handle=u.handle, name=u.name, title=u.title, email=f"{u.handle}@lumen.dev")
            for u in seed_data.USERS
        )
        await session.flush()
        session.add_all(
            TeamRow(id=tid, name=name, org_id=seed_data.ORG[0]) for tid, name in seed_data.TEAMS
        )
        for folder in sorted(seed_data.FOLDERS, key=lambda f: f.parent_id is not None):
            session.add(
                FolderRow(
                    id=folder.id,
                    org_id=seed_data.ORG[0],
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
    print(f"  workspaces schema: {len(seed_data.DOCUMENTS)} documents")


async def replay_traffic(container: Container) -> None:
    principal = Principal(key_id=None, name="seed", scopes=frozenset(Scope), store_id=None)
    rng = random.Random(7)
    for _ in range(260):
        obj, relation, user = rng.choice(seed_data.SAMPLE_TRAFFIC)
        request = CheckRequest(tuple_key=TupleKey(object=obj, relation=relation, user=user))
        await container.queries.check(WORKSPACES_STORE, request, principal)
    for user in ("anne", "dev", "fatima", "ben"):
        await container.queries.list_objects(
            WORKSPACES_STORE,
            ListObjectsRequest(object_type="document", relation="can_view", user=f"user:{user}"),
            principal,
        )
    for obj, relation, user in (
        ("repo:warden", "writer", "user:lin"),
        ("repo:console", "admin", "user:mona"),
        ("repo:docs", "reader", "user:anyone"),
        ("repo:console", "writer", "user:guest"),
    ):
        request = CheckRequest(tuple_key=TupleKey(object=obj, relation=relation, user=user))
        await container.queries.check(GIT_STORE, request, principal)
    await container.decision_log.flush()
    async with container.db.transaction() as session:
        # Spread the synthetic traffic over the last day so the timeline chart has shape.
        await session.execute(
            text(
                "UPDATE decisions SET created_at = now() - (random() * interval '23 hours') "
                "WHERE store_id IN (:a, :b)"
            ),
            {"a": WORKSPACES_STORE, "b": GIT_STORE},
        )
    print("  replayed 268 decisions across the last 24h")


async def main(*, reset: bool) -> None:
    settings = Settings(decision_log="sync", gc_enabled=False)
    config = Config(str(ROOT / "backend" / "alembic.ini"))
    config.attributes["database_url"] = settings.database_url
    await asyncio.to_thread(command.upgrade, config, "head")
    print("migrated warden schema")

    workspaces = WorkspacesSettings()
    console_key = SeedSettings().console_api_key
    container = Container.build(settings)
    await container.start()
    try:
        if console_key is not None:
            await provision_console_key(container, console_key.get_secret_value())
        if not reset and await _store_exists(container, WORKSPACES_STORE):
            print("demo data already present; run with --reset to rebuild it")
            return
        print("seeding warden")
        await seed_warden(container, workspaces.warden_api_key.get_secret_value())
        print("seeding workspaces")
        await seed_workspaces(workspaces.database_url)
        print("replaying traffic")
        await replay_traffic(container)
    finally:
        await container.close()
    print("done")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--reset", action="store_true", help="drop and rebuild the demo stores")
    asyncio.run(main(reset=parser.parse_args().reset))
