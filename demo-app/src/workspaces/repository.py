from __future__ import annotations

from collections.abc import Collection, Sequence

from sqlalchemy import delete, func, select, update

from workspaces.db import Database, DocumentRow, FolderRow, TeamRow, UserRow


class WorkspaceRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def users(self) -> Sequence[UserRow]:
        async with self._db.sessions() as session:
            return (await session.scalars(select(UserRow).order_by(UserRow.name))).all()

    async def user(self, handle: str) -> UserRow | None:
        async with self._db.sessions() as session:
            return await session.get(UserRow, handle)

    async def teams(self) -> Sequence[TeamRow]:
        async with self._db.sessions() as session:
            return (await session.scalars(select(TeamRow).order_by(TeamRow.name))).all()

    async def folders(self, ids: Collection[str]) -> Sequence[FolderRow]:
        if not ids:
            return []
        stmt = select(FolderRow).where(FolderRow.id.in_(ids)).order_by(FolderRow.name)
        async with self._db.sessions() as session:
            return (await session.scalars(stmt)).all()

    async def folder(self, folder_id: str) -> FolderRow | None:
        async with self._db.sessions() as session:
            return await session.get(FolderRow, folder_id)

    async def documents_in_folder(self, folder_id: str) -> Sequence[DocumentRow]:
        stmt = (
            select(DocumentRow)
            .where(DocumentRow.folder_id == folder_id)
            .order_by(DocumentRow.updated_at.desc())
        )
        async with self._db.sessions() as session:
            return (await session.scalars(stmt)).all()

    async def document(self, document_id: str) -> DocumentRow | None:
        async with self._db.sessions() as session:
            return await session.get(DocumentRow, document_id)

    async def create_document(self, row: DocumentRow) -> DocumentRow:
        async with self._db.sessions() as session, session.begin():
            session.add(row)
        return row

    async def update_document(
        self, document_id: str, *, title: str | None, body: str | None
    ) -> DocumentRow | None:
        values: dict[str, object] = {"updated_at": func.now()}
        if title is not None:
            values["title"] = title
        if body is not None:
            values["body"] = body
        async with self._db.sessions() as session, session.begin():
            await session.execute(
                update(DocumentRow).where(DocumentRow.id == document_id).values(**values)
            )
        return await self.document(document_id)

    async def delete_document(self, document_id: str) -> None:
        async with self._db.sessions() as session, session.begin():
            await session.execute(delete(DocumentRow).where(DocumentRow.id == document_id))
