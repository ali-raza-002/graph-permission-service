from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from warden.api.deps import ContainerDep, Cursor, PageSize, require
from warden.auth.keys import Principal, Scope
from warden.core.consistency import Consistency, ConsistencyMode
from warden.core.pagination import DEFAULT_PAGE_SIZE, Page
from warden.tuples.schemas import TupleChange, TupleFilter, WriteCommand, WriteResult
from warden.tuples.service import TuplePage

router = APIRouter(prefix="/v1/stores/{store_id}", tags=["tuples"])


@router.post("/tuples/write")
async def write_tuples(
    store_id: str,
    body: WriteCommand,
    container: ContainerDep,
    _: Annotated[Principal, Depends(require(Scope.TUPLES_WRITE))],
) -> WriteResult:
    """Atomically apply writes and deletes, returning the new revision and its token."""
    return await container.tuples.write(store_id, body)


@router.get("/tuples")
async def read_tuples(
    store_id: str,
    container: ContainerDep,
    _: Annotated[Principal, Depends(require(Scope.TUPLES_READ))],
    object_type: Annotated[str | None, Query(max_length=64)] = None,
    object_id: Annotated[str | None, Query(max_length=256)] = None,
    relation: Annotated[str | None, Query(max_length=64)] = None,
    user: Annotated[str | None, Query(max_length=400)] = None,
    consistency_token: Annotated[str | None, Query(max_length=512)] = None,
    limit: PageSize = DEFAULT_PAGE_SIZE,
    cursor: Cursor = None,
) -> TuplePage:
    """Page through live tuples. Later pages are read at the first page's revision, and
    `consistency_token` only applies to the first page."""
    consistency = (
        Consistency(mode=ConsistencyMode.AT_LEAST_AS_FRESH, token=consistency_token)
        if consistency_token
        else Consistency(mode=ConsistencyMode.FULLY_CONSISTENT)
    )
    return await container.tuples.read(
        store_id,
        TupleFilter(object_type=object_type, object_id=object_id, relation=relation, user=user),
        consistency=consistency,
        limit=limit,
        cursor=cursor,
    )


@router.get("/changes")
async def read_changes(
    store_id: str,
    container: ContainerDep,
    _: Annotated[Principal, Depends(require(Scope.TUPLES_READ))],
    limit: PageSize = DEFAULT_PAGE_SIZE,
    cursor: Cursor = None,
) -> Page[TupleChange]:
    await container.stores.ensure_exists(store_id)
    return await container.tuples.changes(store_id, limit=limit, cursor=cursor)
