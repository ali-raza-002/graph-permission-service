from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field

from warden.api.deps import ContainerDep, Cursor, PageSize, require
from warden.auth.keys import Principal, Scope
from warden.core.errors import NotFoundError
from warden.core.pagination import DEFAULT_PAGE_SIZE, Page, decode_str_cursor
from warden.decisions.schemas import DecisionStats
from warden.model.schemas import ModelSummary, Store

router = APIRouter(prefix="/v1/stores", tags=["stores"])


class CreateStoreRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class CacheInfo(BaseModel):
    """Check cache counters for this API process across every store. Entries are keyed
    per store, but hit and miss counters are not."""

    scope: Literal["service"] = "service"
    backend: Literal["memory", "redis", "none"]
    hits: int
    misses: int
    hit_rate: float


class StoreOverview(BaseModel):
    store: Store
    latest_model: ModelSummary | None
    model_count: int
    tuple_count: int
    tuples_by_type: dict[str, int]
    decisions: DecisionStats
    cache: CacheInfo


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_store(
    body: CreateStoreRequest,
    container: ContainerDep,
    _: Annotated[Principal, Depends(require(Scope.STORES_ADMIN))],
) -> Store:
    return await container.stores.create(body.name)


@router.get("")
async def list_stores(
    container: ContainerDep,
    principal: Annotated[Principal, Depends(require(Scope.MODELS_READ))],
    limit: PageSize = DEFAULT_PAGE_SIZE,
    cursor: Cursor = None,
) -> Page[Store]:
    if principal.store_id is not None:
        return Page[Store](items=[await container.stores.get(principal.store_id)])
    return await container.stores.page(limit=limit, cursor=decode_str_cursor(cursor))


@router.get("/{store_id}")
async def get_store(
    store_id: str,
    container: ContainerDep,
    _: Annotated[Principal, Depends(require(Scope.MODELS_READ))],
) -> Store:
    return await container.stores.get(store_id)


@router.delete("/{store_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_store(
    store_id: str,
    container: ContainerDep,
    _: Annotated[Principal, Depends(require(Scope.STORES_ADMIN))],
) -> Response:
    await container.stores.delete(store_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{store_id}/overview")
async def store_overview(
    store_id: str,
    container: ContainerDep,
    _: Annotated[Principal, Depends(require(Scope.DECISIONS_READ))],
    window_hours: Annotated[int, Query(ge=1, le=24 * 30)] = 24,
) -> StoreOverview:
    store = await container.stores.get(store_id)
    try:
        latest: ModelSummary | None = await container.models.latest(store_id)
    except NotFoundError:
        latest = None
    by_type = await container.tuples.counts(store_id)
    stats = container.cache.stats
    return StoreOverview(
        store=store,
        latest_model=ModelSummary.model_validate(latest.model_dump()) if latest else None,
        model_count=await container.models.count(store_id),
        tuple_count=sum(by_type.values()),
        tuples_by_type=by_type,
        decisions=await container.decisions.stats(store_id, window_hours=window_hours),
        cache=CacheInfo(
            backend=container.settings.cache_backend,
            hits=stats.hits,
            misses=stats.misses,
            hit_rate=round(stats.hit_rate, 4),
        ),
    )
