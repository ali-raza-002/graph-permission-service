from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from warden.api.deps import ContainerDep, Cursor, PageSize, require
from warden.auth.keys import Principal, Scope
from warden.core.pagination import DEFAULT_PAGE_SIZE, Page, decode_str_cursor
from warden.decisions.schemas import Decision, DecisionKind, DecisionStats, DecisionSummary

router = APIRouter(prefix="/v1/stores/{store_id}/decisions", tags=["decisions"])

DecisionsPrincipal = Annotated[Principal, Depends(require(Scope.DECISIONS_READ))]


@router.get("")
async def list_decisions(
    store_id: str,
    container: ContainerDep,
    _: DecisionsPrincipal,
    allowed: bool | None = None,
    kind: DecisionKind | None = None,
    subject: Annotated[str | None, Query(max_length=400)] = None,
    object: Annotated[str | None, Query(max_length=330)] = None,  # noqa: A002
    limit: PageSize = DEFAULT_PAGE_SIZE,
    cursor: Cursor = None,
) -> Page[DecisionSummary]:
    await container.stores.ensure_exists(store_id)
    return await container.decisions.page(
        store_id,
        limit=limit,
        cursor=decode_str_cursor(cursor),
        allowed=allowed,
        kind=kind,
        subject=subject,
        obj=object,
    )


@router.get("/stats")
async def decision_stats(
    store_id: str,
    container: ContainerDep,
    _: DecisionsPrincipal,
    window_hours: Annotated[int, Query(ge=1, le=24 * 30)] = 24,
) -> DecisionStats:
    await container.stores.ensure_exists(store_id)
    return await container.decisions.stats(store_id, window_hours=window_hours)


@router.get("/{decision_id}")
async def get_decision(
    store_id: str, decision_id: str, container: ContainerDep, _: DecisionsPrincipal
) -> Decision:
    return await container.decisions.get(store_id, decision_id)
