from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from warden.api.deps import ContainerDep, require
from warden.auth.keys import Principal, Scope
from warden.queries.schemas import (
    BatchCheckRequest,
    BatchCheckResponse,
    CheckRequest,
    CheckResponse,
    ExpandRequest,
    ExpandResponse,
    ListObjectsRequest,
    ListObjectsResponse,
    ListUsersRequest,
    ListUsersResponse,
)

router = APIRouter(prefix="/v1/stores/{store_id}", tags=["queries"])

CheckPrincipal = Annotated[Principal, Depends(require(Scope.CHECK))]


@router.post("/check")
async def check(
    store_id: str, body: CheckRequest, container: ContainerDep, principal: CheckPrincipal
) -> CheckResponse:
    """Decide whether `user` has `relation` on `object`, with a full resolution trace."""
    return await container.queries.check(store_id, body, principal)


@router.post("/batch-check")
async def batch_check(
    store_id: str, body: BatchCheckRequest, container: ContainerDep, principal: CheckPrincipal
) -> BatchCheckResponse:
    return await container.queries.batch_check(store_id, body, principal)


@router.post("/expand")
async def expand(
    store_id: str, body: ExpandRequest, container: ContainerDep, _: CheckPrincipal
) -> ExpandResponse:
    return await container.queries.expand(store_id, body)


@router.post("/list-objects")
async def list_objects(
    store_id: str, body: ListObjectsRequest, container: ContainerDep, principal: CheckPrincipal
) -> ListObjectsResponse:
    return await container.queries.list_objects(store_id, body, principal)


@router.post("/list-users")
async def list_users(
    store_id: str, body: ListUsersRequest, container: ContainerDep, principal: CheckPrincipal
) -> ListUsersResponse:
    return await container.queries.list_users(store_id, body, principal)
