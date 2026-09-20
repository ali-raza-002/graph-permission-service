from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from warden_sdk import WardenClient
from warden_sdk.fastapi import WardenGuard
from workspaces.repository import WorkspaceRepository
from workspaces.schemas import User
from workspaces.service import WorkspaceService


def get_warden(request: Request) -> WardenClient:
    client: WardenClient = request.app.state.warden
    return client


def get_repository(request: Request) -> WorkspaceRepository:
    repository: WorkspaceRepository = request.app.state.repository
    return repository


def get_service(request: Request) -> WorkspaceService:
    service: WorkspaceService = request.app.state.service
    return service


async def current_user(
    repository: Annotated[WorkspaceRepository, Depends(get_repository)],
    x_workspaces_user: Annotated[str | None, Header()] = None,
) -> User:
    """Demo identity: the caller names themselves in a header. A real deployment would
    resolve the session here; authorization is the part this app demonstrates."""
    if not x_workspaces_user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "send X-Workspaces-User")
    row = await repository.user(x_workspaces_user)
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown user")
    return User.model_validate(row)


def current_subject(user: Annotated[User, Depends(current_user)]) -> str:
    return user.subject


guard = WardenGuard(client=get_warden, subject=current_subject)

can_view_folder = guard.require("viewer", "folder", "folder_id")
can_edit_folder = guard.require("editor", "folder", "folder_id")
can_view_document = guard.require("can_view", "document", "document_id")
can_edit_document = guard.require("can_edit", "document", "document_id")
can_share_document = guard.require("can_share", "document", "document_id")
can_delete_document = guard.require("can_delete", "document", "document_id")

CurrentUser = Annotated[User, Depends(current_user)]
Service = Annotated[WorkspaceService, Depends(get_service)]
