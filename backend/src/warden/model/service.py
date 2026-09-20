from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from warden.core.errors import NotFoundError
from warden.core.pagination import Page, encode_cursor
from warden.db.tables import ModelRow
from warden.dsl import AuthorizationModel, TypeSystem, compile_model
from warden.model.repository import ModelRepository, StoreRepository
from warden.model.schemas import ModelDetail, ModelSummary, Store

_LATEST_TTL_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class ResolvedModel:
    id: str
    store_id: str
    version: int
    typesystem: TypeSystem


class StoreService:
    def __init__(
        self, stores: StoreRepository, *, on_delete: Sequence[Callable[[str], None]] = ()
    ) -> None:
        self._stores = stores
        self._on_delete = tuple(on_delete)

    async def create(self, name: str) -> Store:
        return Store.model_validate(await self._stores.create(name))

    async def get(self, store_id: str) -> Store:
        row = await self._stores.get(store_id)
        if row is None:
            raise NotFoundError(f"store '{store_id}' does not exist")
        return Store.model_validate(row)

    async def ensure_exists(self, store_id: str) -> None:
        await self.get(store_id)

    async def page(self, *, limit: int, cursor: str | None) -> Page[Store]:
        rows = await self._stores.page(limit=limit + 1, before=cursor)
        items = [Store.model_validate(r) for r in rows[:limit]]
        next_cursor = encode_cursor(items[-1].id) if len(rows) > limit and items else None
        return Page[Store](items=items, next_cursor=next_cursor)

    async def delete(self, store_id: str) -> None:
        if not await self._stores.soft_delete(store_id):
            raise NotFoundError(f"store '{store_id}' does not exist")
        for forget in self._on_delete:
            forget(store_id)


class ModelService:
    """Versioned authorization models. Compiled models are immutable, so the
    TypeSystem for a given model id is cached for the life of the process."""

    def __init__(
        self, stores: StoreRepository, models: ModelRepository, *, cache_size: int = 256
    ) -> None:
        self._stores = stores
        self._models = models
        self._cache_size = cache_size
        self._typesystems: OrderedDict[str, ResolvedModel] = OrderedDict()
        self._latest: dict[str, tuple[str, float]] = {}

    async def write(self, store_id: str, dsl: str) -> ModelDetail:
        if await self._stores.get(store_id) is None:
            raise NotFoundError(f"store '{store_id}' does not exist")
        model = compile_model(dsl)
        row = await self._models.create(
            store_id,
            dsl=dsl,
            ast=model.model_dump(mode="json"),
            schema_version=model.schema_version,
        )
        self._remember(row, model)
        self._latest[store_id] = (row.id, time.monotonic())
        return _detail(row)

    async def get(self, store_id: str, model_id: str) -> ModelDetail:
        row = await self._models.get(store_id, model_id)
        if row is None:
            raise NotFoundError(f"model '{model_id}' does not exist in store '{store_id}'")
        return _detail(row)

    async def latest(self, store_id: str) -> ModelDetail:
        row = await self._models.latest(store_id)
        if row is None:
            raise NotFoundError(f"store '{store_id}' has no authorization model yet")
        return _detail(row)

    async def page(self, store_id: str, *, limit: int, cursor: int | None) -> Page[ModelSummary]:
        rows = await self._models.page(store_id, limit=limit + 1, before_version=cursor)
        items = [ModelSummary.model_validate(r) for r in rows[:limit]]
        next_cursor = encode_cursor(items[-1].version) if len(rows) > limit and items else None
        return Page[ModelSummary](items=items, next_cursor=next_cursor)

    def forget_store(self, store_id: str) -> None:
        self._latest.pop(store_id, None)
        for model_id in [k for k, v in self._typesystems.items() if v.store_id == store_id]:
            del self._typesystems[model_id]

    async def count(self, store_id: str) -> int:
        return await self._models.count(store_id)

    async def resolve(self, store_id: str, model_id: str | None = None) -> ResolvedModel:
        """Pin a model id (or the latest one) and return its compiled type system."""
        if model_id is None:
            model_id = await self._latest_id(store_id)
        cached = self._typesystems.get(model_id)
        if cached is not None and cached.store_id == store_id:
            self._typesystems.move_to_end(model_id)
            return cached
        row = await self._models.get(store_id, model_id)
        if row is None:
            raise NotFoundError(f"model '{model_id}' does not exist in store '{store_id}'")
        return self._remember(row, AuthorizationModel.model_validate(row.ast))

    async def _latest_id(self, store_id: str) -> str:
        hit = self._latest.get(store_id)
        if hit is not None and time.monotonic() - hit[1] < _LATEST_TTL_SECONDS:
            return hit[0]
        row = await self._models.latest(store_id)
        if row is None:
            raise NotFoundError(f"store '{store_id}' has no authorization model yet")
        self._latest[store_id] = (row.id, time.monotonic())
        return row.id

    def _remember(self, row: ModelRow, model: AuthorizationModel) -> ResolvedModel:
        resolved = ResolvedModel(
            id=row.id, store_id=row.store_id, version=row.version, typesystem=TypeSystem(model)
        )
        self._typesystems[row.id] = resolved
        while len(self._typesystems) > self._cache_size:
            self._typesystems.popitem(last=False)
        return resolved


def _detail(row: ModelRow) -> ModelDetail:
    return ModelDetail(
        id=row.id,
        store_id=row.store_id,
        version=row.version,
        schema_version=row.schema_version,
        created_at=row.created_at,
        dsl=row.dsl,
        ast=AuthorizationModel.model_validate(row.ast),
    )
