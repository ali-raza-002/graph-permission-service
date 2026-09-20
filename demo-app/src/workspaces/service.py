"""Workspace use cases. Every permission question is answered by Warden; this module
only decides which question to ask."""

from __future__ import annotations

import re
import secrets
from collections.abc import Sequence

from warden_sdk import CheckResult, TupleKey, WardenClient
from workspaces.db import DocumentRow
from workspaces.repository import WorkspaceRepository
from workspaces.schemas import (
    Access,
    Authorization,
    Document,
    DocumentCreate,
    DocumentDetail,
    DocumentSummary,
    DocumentUpdate,
    Folder,
    FolderDetail,
    Permissions,
    Share,
    ShareView,
    User,
)

ORG_ID = "lumen"
# Warden's default per-request limits for batch checks and tuple writes.
_BATCH_CHECK_SIZE = 100
_WRITE_CHUNK = 200


def _authorization(result: CheckResult) -> Authorization:
    return Authorization(
        decision_id=result.decision_id, revision=result.revision, duration_ms=result.duration_ms
    )


def _slug(title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48] or "document"
    return f"{base}-{secrets.token_hex(3)}"


class NotFoundError(Exception):
    pass


class ForbiddenError(Exception):
    def __init__(self, message: str, decision_id: str) -> None:
        super().__init__(message)
        self.decision_id = decision_id


def _not_found(kind: str) -> NotFoundError:
    return NotFoundError(f"{kind} not found")


class WorkspaceService:
    def __init__(self, repository: WorkspaceRepository, warden: WardenClient) -> None:
        self._repo = repository
        self._warden = warden

    async def visible_folders(self, user: User) -> list[Folder]:
        visible = await self._warden.list_objects("folder", "viewer", user.subject)
        return [Folder.model_validate(f) for f in await self._repo.folders(visible.ids)]

    async def folder_detail(
        self, user: User, folder_id: str, decision: CheckResult
    ) -> FolderDetail:
        folder = await self._repo.folder(folder_id)
        if folder is None:
            raise _not_found("folder")
        # Ask only about this folder's documents. list_objects would walk every document
        # the user can see anywhere in the org just to filter it down to one folder.
        candidates = await self._repo.documents_in_folder(folder_id)
        readable = await self._readable(user, [d.id for d in candidates])
        documents = [d for d in candidates if d.id in readable]
        can_create = await self._warden.check(f"folder:{folder_id}", "editor", user.subject)
        return FolderDetail(
            folder=Folder.model_validate(folder),
            documents=[DocumentSummary.model_validate(d) for d in documents],
            can_create=can_create.allowed,
            authorization=_authorization(decision),
        )

    async def create_document(
        self, user: User, folder_id: str, data: DocumentCreate
    ) -> DocumentDetail:
        folder = await self._repo.folder(folder_id)
        if folder is None:
            raise _not_found("folder")
        row = DocumentRow(
            id=_slug(data.title),
            folder_id=folder_id,
            title=data.title,
            body=data.body,
            created_by=user.handle,
        )
        # Relationships go in first: a document Warden does not know about is merely
        # invisible, while a row without tuples would be an orphan nobody can open.
        await self._warden.write(
            [
                f"document:{row.id}#parent@folder:{folder_id}",
                f"document:{row.id}#org@org:{folder.org_id}",
                f"document:{row.id}#owner@{user.subject}",
            ]
        )
        await self._repo.create_document(row)
        return await self.document_detail(
            user, row.id, await self._warden.check(f"document:{row.id}", "can_view", user.subject)
        )

    async def document_detail(
        self, user: User, document_id: str, decision: CheckResult
    ) -> DocumentDetail:
        row = await self._repo.document(document_id)
        if row is None:
            raise _not_found("document")
        obj = f"document:{document_id}"
        flags = await self._warden.batch_check(
            {
                "can_edit": f"{obj}#can_edit@{user.subject}",
                "can_share": f"{obj}#can_share@{user.subject}",
                "can_delete": f"{obj}#can_delete@{user.subject}",
            }
        )
        return DocumentDetail(
            document=Document.model_validate(row),
            permissions=Permissions(**flags),
            authorization=_authorization(decision),
        )

    async def update_document(
        self, user: User, document_id: str, data: DocumentUpdate, decision: CheckResult
    ) -> DocumentDetail:
        if await self._repo.update_document(document_id, title=data.title, body=data.body) is None:
            raise _not_found("document")
        return await self.document_detail(user, document_id, decision)

    async def delete_document(self, document_id: str) -> None:
        if await self._repo.document(document_id) is None:
            raise _not_found("document")
        # Tuples go first. If Warden fails halfway the row is still there and the delete
        # can simply be retried; the reverse order would strand tuples for a ghost document.
        tuples = await self._document_tuples(document_id)
        for start in range(0, len(tuples), _WRITE_CHUNK):
            await self._warden.write(
                deletes=tuples[start : start + _WRITE_CHUNK], on_missing="ignore"
            )
        await self._repo.delete_document(document_id)

    async def access(self, user: User, document_id: str) -> Access:
        if await self._repo.document(document_id) is None:
            raise _not_found("document")
        obj = f"document:{document_id}"
        tuples = await self._document_tuples(document_id)
        viewers = await self._warden.list_users(obj, "can_view", "user")
        flags = await self._warden.batch_check(
            {
                "can_share": f"{obj}#can_share@{user.subject}",
                "can_manage": f"{obj}#can_manage_access@{user.subject}",
            }
        )
        return Access(
            owner=[t.user for t in tuples if t.relation == "owner"],
            shares=[
                ShareView.model_validate({"subject": t.user, "role": t.relation})
                for t in tuples
                if t.relation in {"viewer", "editor", "blocked"}
            ],
            effective_viewers=viewers.users,
            can_share=flags["can_share"],
            can_manage=flags["can_manage"],
        )

    async def share(self, user: User, document_id: str, share: Share) -> Access:
        if share.role == "blocked":
            await self._require_manage(user, document_id, "block people")
        await self._warden.write(
            [f"document:{document_id}#{share.role}@{share.subject}"], on_duplicate="ignore"
        )
        return await self.access(user, document_id)

    async def unshare(self, user: User, document_id: str, share: Share) -> Access:
        await self._require_manage(user, document_id, "remove shares")
        await self._warden.write(
            deletes=[f"document:{document_id}#{share.role}@{share.subject}"], on_missing="ignore"
        )
        return await self.access(user, document_id)

    async def _require_manage(self, user: User, document_id: str, action: str) -> None:
        decision = await self._warden.check(
            f"document:{document_id}", "can_manage_access", user.subject
        )
        if not decision.allowed:
            raise ForbiddenError(
                f"only the owner or an org admin can {action}", decision.decision_id
            )

    async def _readable(self, user: User, document_ids: Sequence[str]) -> set[str]:
        readable: set[str] = set()
        for start in range(0, len(document_ids), _BATCH_CHECK_SIZE):
            chunk = document_ids[start : start + _BATCH_CHECK_SIZE]
            verdicts = await self._warden.batch_check(
                {doc_id: f"document:{doc_id}#can_view@{user.subject}" for doc_id in chunk}
            )
            readable.update(doc_id for doc_id, allowed in verdicts.items() if allowed)
        return readable

    async def _document_tuples(self, document_id: str) -> list[TupleKey]:
        tuples: list[TupleKey] = []
        cursor: str | None = None
        while True:
            page = await self._warden.read(
                object_type="document", object_id=document_id, limit=200, cursor=cursor
            )
            tuples.extend(t.key for t in page.items)
            if page.next_cursor is None:
                return tuples
            cursor = page.next_cursor
