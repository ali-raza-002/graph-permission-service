from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from warden_sdk import CheckResult
from workspaces.deps import (
    CurrentUser,
    Service,
    can_delete_document,
    can_edit_document,
    can_edit_folder,
    can_share_document,
    can_view_document,
    can_view_folder,
    get_repository,
)
from workspaces.repository import WorkspaceRepository
from workspaces.schemas import (
    Access,
    DocumentCreate,
    DocumentDetail,
    DocumentUpdate,
    Folder,
    FolderDetail,
    Share,
    Team,
    User,
)

router = APIRouter(prefix="/api", tags=["workspaces"])

Repository = Annotated[WorkspaceRepository, Depends(get_repository)]


@router.get("/users")
async def list_users(repository: Repository) -> list[User]:
    return [User.model_validate(u) for u in await repository.users()]


@router.get("/teams")
async def list_teams(repository: Repository) -> list[Team]:
    return [Team.model_validate(t) for t in await repository.teams()]


@router.get("/me")
async def me(user: CurrentUser) -> User:
    return user


@router.get("/folders")
async def list_folders(user: CurrentUser, service: Service) -> list[Folder]:
    return await service.visible_folders(user)


@router.get("/folders/{folder_id}")
async def folder_detail(
    folder_id: str,
    user: CurrentUser,
    service: Service,
    decision: Annotated[CheckResult, Depends(can_view_folder)],
) -> FolderDetail:
    return await service.folder_detail(user, folder_id, decision)


@router.post(
    "/folders/{folder_id}/documents",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(can_edit_folder)],
)
async def create_document(
    folder_id: str, body: DocumentCreate, user: CurrentUser, service: Service
) -> DocumentDetail:
    return await service.create_document(user, folder_id, body)


@router.get("/documents/{document_id}")
async def document_detail(
    document_id: str,
    user: CurrentUser,
    service: Service,
    decision: Annotated[CheckResult, Depends(can_view_document)],
) -> DocumentDetail:
    return await service.document_detail(user, document_id, decision)


@router.patch("/documents/{document_id}")
async def update_document(
    document_id: str,
    body: DocumentUpdate,
    user: CurrentUser,
    service: Service,
    decision: Annotated[CheckResult, Depends(can_edit_document)],
) -> DocumentDetail:
    return await service.update_document(user, document_id, body, decision)


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(can_delete_document)],
)
async def delete_document(document_id: str, service: Service) -> Response:
    await service.delete_document(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/documents/{document_id}/access", dependencies=[Depends(can_view_document)])
async def document_access(document_id: str, user: CurrentUser, service: Service) -> Access:
    return await service.access(user, document_id)


@router.post("/documents/{document_id}/shares", dependencies=[Depends(can_share_document)])
async def share_document(
    document_id: str, body: Share, user: CurrentUser, service: Service
) -> Access:
    return await service.share(user, document_id, body)


@router.post("/documents/{document_id}/unshare", dependencies=[Depends(can_share_document)])
async def unshare_document(
    document_id: str, body: Share, user: CurrentUser, service: Service
) -> Access:
    return await service.unshare(user, document_id, body)
