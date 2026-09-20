from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from warden.auth.keys import Principal, Scope
from warden.container import Container
from warden.core.errors import AuthenticationError
from warden.core.pagination import MAX_PAGE_SIZE

_bearer = HTTPBearer(auto_error=False, description="API key, e.g. 'Bearer wdn_ab12cd34_...'")


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


async def authenticate(
    container: ContainerDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("missing bearer API key")
    return await container.keys.authenticate(credentials.credentials)


def require(scope: Scope) -> Callable[..., Awaitable[Principal]]:
    """Dependency that authenticates the caller and checks scope plus store binding."""

    async def dependency(
        request: Request, principal: Annotated[Principal, Depends(authenticate)]
    ) -> Principal:
        principal.authorize(scope, request.path_params.get("store_id"))
        return principal

    return dependency


PageSize = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
Cursor = Annotated[str | None, Query(max_length=512)]
