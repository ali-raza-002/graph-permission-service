from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, func, select, update

from warden.core.ids import new_id
from warden.db.database import Database
from warden.db.tables import ModelRow, StoreRow


class StoreRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, name: str, *, store_id: str | None = None) -> StoreRow:
        async with self._db.transaction() as session:
            row = StoreRow(id=store_id or new_id("st"), name=name, revision=0)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return row

    async def get(self, store_id: str) -> StoreRow | None:
        async with self._db.session() as session:
            row = await session.get(StoreRow, store_id)
            return row if row is not None and row.deleted_at is None else None

    async def page(self, *, limit: int, before: str | None = None) -> Sequence[StoreRow]:
        stmt = select(StoreRow).where(StoreRow.deleted_at.is_(None))
        if before is not None:
            stmt = stmt.where(StoreRow.id < before)
        stmt = stmt.order_by(StoreRow.id.desc()).limit(limit)
        async with self._db.session() as session:
            return (await session.scalars(stmt)).all()

    async def soft_delete(self, store_id: str) -> bool:
        stmt = (
            update(StoreRow)
            .where(StoreRow.id == store_id, StoreRow.deleted_at.is_(None))
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        async with self._db.transaction() as session:
            result = await session.execute(stmt)
            return bool(getattr(result, "rowcount", 0))

    async def revision(self, store_id: str) -> int | None:
        bounds = await self.revision_bounds(store_id)
        return bounds[0] if bounds is not None else None

    async def revision_bounds(self, store_id: str) -> tuple[int, int] | None:
        """The current revision and the oldest revision still readable."""
        stmt = select(StoreRow.revision, StoreRow.gc_revision).where(
            StoreRow.id == store_id, StoreRow.deleted_at.is_(None)
        )
        async with self._db.connect() as conn:
            row = (await conn.execute(stmt)).one_or_none()
            return (int(row[0]), int(row[1])) if row is not None else None


def _live_store(store_id: str) -> ColumnElement[bool]:
    return ModelRow.store_id.in_(
        select(StoreRow.id).where(StoreRow.id == store_id, StoreRow.deleted_at.is_(None))
    )


class ModelRepository:
    """Model reads only see models of live stores, so a deleted store's models vanish
    with it even though the rows stay until garbage collection."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self, store_id: str, *, dsl: str, ast: dict[str, Any], schema_version: str
    ) -> ModelRow:
        async with self._db.transaction() as session:
            # Locking the store row serializes concurrent model writes so versions stay dense.
            await session.execute(
                select(StoreRow.id).where(StoreRow.id == store_id).with_for_update()
            )
            current = await session.scalar(
                select(func.coalesce(func.max(ModelRow.version), 0)).where(
                    ModelRow.store_id == store_id
                )
            )
            row = ModelRow(
                id=new_id("md"),
                store_id=store_id,
                version=int(current or 0) + 1,
                schema_version=schema_version,
                dsl=dsl,
                ast=ast,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return row

    async def get(self, store_id: str, model_id: str) -> ModelRow | None:
        stmt = select(ModelRow).where(
            ModelRow.store_id == store_id, ModelRow.id == model_id, _live_store(store_id)
        )
        async with self._db.session() as session:
            return (await session.scalars(stmt)).one_or_none()

    async def latest(self, store_id: str) -> ModelRow | None:
        stmt = (
            select(ModelRow)
            .where(ModelRow.store_id == store_id, _live_store(store_id))
            .order_by(ModelRow.version.desc())
            .limit(1)
        )
        async with self._db.session() as session:
            return (await session.scalars(stmt)).one_or_none()

    async def page(
        self, store_id: str, *, limit: int, before_version: int | None = None
    ) -> Sequence[ModelRow]:
        stmt = select(ModelRow).where(ModelRow.store_id == store_id)
        if before_version is not None:
            stmt = stmt.where(ModelRow.version < before_version)
        stmt = stmt.order_by(ModelRow.version.desc()).limit(limit)
        async with self._db.session() as session:
            return (await session.scalars(stmt)).all()

    async def count(self, store_id: str) -> int:
        stmt = select(func.count()).select_from(ModelRow).where(ModelRow.store_id == store_id)
        async with self._db.connect() as conn:
            return int((await conn.execute(stmt)).scalar_one())
