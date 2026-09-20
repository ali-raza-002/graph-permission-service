from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from warden.api.deps import ContainerDep, require
from warden.auth.keys import ApiKey, CreatedApiKey, Principal, Scope

router = APIRouter(prefix="/v1/api-keys", tags=["api keys"])

AdminPrincipal = Annotated[Principal, Depends(require(Scope.KEYS_ADMIN))]


class CreateKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    scopes: list[Scope] = Field(min_length=1)
    store_id: str | None = Field(
        default=None, description="Bind the key to one store. Omit for a global key."
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_key(
    body: CreateKeyRequest, container: ContainerDep, _: AdminPrincipal
) -> CreatedApiKey:
    if body.store_id is not None:
        await container.stores.ensure_exists(body.store_id)
    return await container.keys.create(name=body.name, scopes=body.scopes, store_id=body.store_id)


@router.get("")
async def list_keys(
    container: ContainerDep, _: AdminPrincipal, store_id: str | None = None
) -> list[ApiKey]:
    return await container.keys.page(store_id=store_id)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(key_id: str, container: ContainerDep, _: AdminPrincipal) -> Response:
    await container.keys.revoke(key_id, store_id=None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
