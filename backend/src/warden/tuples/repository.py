from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import (
    ColumnElement,
    Executable,
    Select,
    and_,
    func,
    literal,
    or_,
    select,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert

from warden.core.errors import ConflictError, NotFoundError, PreconditionFailedError
from warden.core.refs import WILDCARD, ObjectRef, RelationTuple, SubjectRef
from warden.db.database import Database
from warden.db.tables import RevisionRow, StoreRow, TupleRow
from warden.engine.reader import matches_candidate

_KEY_COLUMNS = (
    TupleRow.object_type,
    TupleRow.object_id,
    TupleRow.relation,
    TupleRow.subject_type,
    TupleRow.subject_id,
    TupleRow.subject_relation,
)

type TupleKeyRow = tuple[str, str, str, str, str, str]
type _ObjectView = dict[str, list[SubjectRef]]


def _key(t: RelationTuple) -> TupleKeyRow:
    s = t.subject
    return (t.object.type, t.object.id, t.relation, s.type, s.id, s.relation or "")


def _from_key(row: Sequence[Any]) -> RelationTuple:
    return RelationTuple(
        ObjectRef(row[0], row[1]), row[2], SubjectRef(row[3], row[4], row[5] or None)
    )


def visible_at(store_id: str, revision: int) -> ColumnElement[bool]:
    return and_(
        TupleRow.store_id == store_id,
        TupleRow.created_revision <= revision,
        or_(TupleRow.deleted_revision.is_(None), TupleRow.deleted_revision > revision),
    )


@dataclass(frozen=True, slots=True)
class TupleRecord:
    id: int
    tuple: RelationTuple
    created_revision: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ChangeRecord:
    id: int
    operation: Literal["write", "delete"]
    revision: int
    tuple: RelationTuple


@dataclass(frozen=True, slots=True)
class WriteOutcome:
    revision: int
    written: int
    deleted: int


class _NothingChanged(Exception):  # noqa: N818 - control flow, never escapes the repository
    def __init__(self, revision: int) -> None:
        self.revision = revision


class TupleRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def write(
        self,
        store_id: str,
        *,
        writes: Sequence[RelationTuple],
        deletes: Sequence[RelationTuple],
        preconditions: Sequence[tuple[RelationTuple, bool]],
        on_duplicate: Literal["error", "ignore"],
        on_missing: Literal["error", "ignore"],
    ) -> WriteOutcome:
        """Apply a batch atomically and stamp it with the next store revision.

        Incrementing the revision takes a row lock on the store, which serializes
        writers per store and guarantees that revision N is fully committed before
        any reader can observe revision N. A batch that changes nothing (every write a
        duplicate and every delete missing, with "ignore") is rolled back so it does not
        burn a revision and invalidate the per-revision check cache.
        """
        try:
            return await self._write(
                store_id,
                writes=writes,
                deletes=deletes,
                preconditions=preconditions,
                on_duplicate=on_duplicate,
                on_missing=on_missing,
            )
        except _NothingChanged as unchanged:
            return WriteOutcome(revision=unchanged.revision, written=0, deleted=0)

    async def _write(
        self,
        store_id: str,
        *,
        writes: Sequence[RelationTuple],
        deletes: Sequence[RelationTuple],
        preconditions: Sequence[tuple[RelationTuple, bool]],
        on_duplicate: Literal["error", "ignore"],
        on_missing: Literal["error", "ignore"],
    ) -> WriteOutcome:
        async with self._db.transaction() as session:
            revision = await session.scalar(
                update(StoreRow)
                .where(StoreRow.id == store_id, StoreRow.deleted_at.is_(None))
                .values(revision=StoreRow.revision + 1, updated_at=func.now())
                .returning(StoreRow.revision)
            )
            if revision is None:
                raise NotFoundError(f"store '{store_id}' does not exist")

            if preconditions:
                keys = [_key(t) for t, _ in preconditions]
                existing = await session.execute(
                    select(*_KEY_COLUMNS).where(
                        TupleRow.store_id == store_id,
                        TupleRow.deleted_revision.is_(None),
                        tuple_(*_KEY_COLUMNS).in_(keys),
                    )
                )
                live = {tuple(row) for row in existing}
                failed = [
                    {"tuple": str(t), "must_exist": must_exist}
                    for t, must_exist in preconditions
                    if (_key(t) in live) != must_exist
                ]
                if failed:
                    raise PreconditionFailedError(
                        f"{len(failed)} precondition(s) did not hold", details=failed
                    )

            deleted = 0
            if deletes:
                keys = [_key(t) for t in deletes]
                result = await session.execute(
                    update(TupleRow)
                    .where(
                        TupleRow.store_id == store_id,
                        TupleRow.deleted_revision.is_(None),
                        tuple_(*_KEY_COLUMNS).in_(keys),
                    )
                    .values(deleted_revision=revision)
                    .returning(*_KEY_COLUMNS)
                )
                removed = {tuple(row) for row in result}
                deleted = len(removed)
                missing = [str(t) for t in deletes if _key(t) not in removed]
                if missing and on_missing == "error":
                    raise ConflictError(
                        f"{len(missing)} tuple(s) to delete do not exist",
                        details=[{"tuple": m} for m in missing],
                    )

            written = 0
            if writes:
                rows = [
                    {
                        "store_id": store_id,
                        "object_type": t.object.type,
                        "object_id": t.object.id,
                        "relation": t.relation,
                        "subject_type": t.subject.type,
                        "subject_id": t.subject.id,
                        "subject_relation": t.subject.relation or "",
                        "created_revision": revision,
                    }
                    for t in writes
                ]
                stmt = (
                    pg_insert(TupleRow)
                    .values(rows)
                    .on_conflict_do_nothing(
                        index_elements=["store_id", *(c.key for c in _KEY_COLUMNS)],
                        index_where=TupleRow.deleted_revision.is_(None),
                    )
                    .returning(*_KEY_COLUMNS)
                )
                inserted = {tuple(row) for row in await session.execute(stmt)}
                written = len(inserted)
                duplicates = [str(t) for t in writes if _key(t) not in inserted]
                if duplicates and on_duplicate == "error":
                    raise ConflictError(
                        f"{len(duplicates)} tuple(s) already exist",
                        details=[{"tuple": d} for d in duplicates],
                    )
            if written == 0 and deleted == 0:
                raise _NothingChanged(int(revision) - 1)
            session.add(RevisionRow(store_id=store_id, revision=int(revision)))
            return WriteOutcome(revision=int(revision), written=written, deleted=deleted)

    async def read(
        self,
        store_id: str,
        revision: int,
        *,
        object_type: str | None = None,
        object_id: str | None = None,
        relation: str | None = None,
        subject: SubjectRef | None = None,
        limit: int,
        after_id: int | None = None,
    ) -> list[TupleRecord]:
        stmt = select(
            TupleRow.id, *_KEY_COLUMNS, TupleRow.created_revision, TupleRow.created_at
        ).where(visible_at(store_id, revision))
        if object_type:
            stmt = stmt.where(TupleRow.object_type == object_type)
        if object_id:
            stmt = stmt.where(TupleRow.object_id == object_id)
        if relation:
            stmt = stmt.where(TupleRow.relation == relation)
        if subject is not None:
            stmt = stmt.where(
                TupleRow.subject_type == subject.type,
                TupleRow.subject_id == subject.id,
                TupleRow.subject_relation == (subject.relation or ""),
            )
        if after_id is not None:
            stmt = stmt.where(TupleRow.id > after_id)
        stmt = stmt.order_by(TupleRow.id).limit(limit)
        async with self._db.connect() as conn:
            rows = (await conn.execute(stmt)).all()
        return [
            TupleRecord(id=r[0], tuple=_from_key(r[1:7]), created_revision=r[7], created_at=r[8])
            for r in rows
        ]

    async def changes(
        self, store_id: str, *, limit: int, before: tuple[int, int] | None = None
    ) -> list[ChangeRecord]:
        """Write and delete events, newest first."""
        writes = select(
            TupleRow.id.label("id"),
            literal("write").label("operation"),
            TupleRow.created_revision.label("revision"),
            *_KEY_COLUMNS,
        ).where(TupleRow.store_id == store_id)
        deletes = select(
            TupleRow.id.label("id"),
            literal("delete").label("operation"),
            TupleRow.deleted_revision.label("revision"),
            *_KEY_COLUMNS,
        ).where(TupleRow.store_id == store_id, TupleRow.deleted_revision.is_not(None))
        events = writes.union_all(deletes).subquery()
        stmt: Select[Any] = select(events)
        if before is not None:
            stmt = stmt.where(tuple_(events.c.revision, events.c.id) < tuple_(*before))
        stmt = stmt.order_by(events.c.revision.desc(), events.c.id.desc()).limit(limit)
        async with self._db.connect() as conn:
            rows = (await conn.execute(stmt)).all()
        return [
            ChangeRecord(id=r[0], operation=r[1], revision=int(r[2]), tuple=_from_key(r[3:9]))
            for r in rows
        ]

    async def count_live(self, store_id: str) -> dict[str, int]:
        stmt = (
            select(TupleRow.object_type, func.count())
            .where(TupleRow.store_id == store_id, TupleRow.deleted_revision.is_(None))
            .group_by(TupleRow.object_type)
            .order_by(func.count().desc())
        )
        async with self._db.connect() as conn:
            return {row[0]: int(row[1]) for row in (await conn.execute(stmt)).all()}


def _discard_result(task: asyncio.Future[Any]) -> None:
    """Mark an orphaned task's exception as retrieved; its caller has already gone."""
    if not task.cancelled():
        task.exception()


class PostgresTupleReader:
    """TupleReader over Postgres pinned to one store revision.

    Every query filters on visibility at that revision, so reads can use any pooled
    connection without sharing a transaction and still see one consistent snapshot.

    During a check the reader loads, in one query per object, every tuple on that
    object the check could use: rows naming the subject (or its wildcard), userset rows
    that need further resolution, and all rows of tupleset relations. Results are
    shared for the rest of the request.
    """

    def __init__(
        self,
        db: Database,
        store_id: str,
        revision: int,
        *,
        tuplesets: Mapping[str, frozenset[str]] | None = None,
    ) -> None:
        self._db = db
        self._store_id = store_id
        self._revision = revision
        self._tuplesets = tuplesets or {}
        self._objects: dict[tuple[ObjectRef, SubjectRef], asyncio.Future[_ObjectView]] = {}
        self.queries = 0

    async def _rows(self, stmt: Executable) -> Sequence[Sequence[Any]]:
        # Short-circuiting cancels sibling sub-checks. The query runs in its own task so
        # a cancelled caller lets it finish and return its pooled connection (and its
        # read slot) instead of abandoning it mid-checkout.
        task = asyncio.ensure_future(self._query(stmt))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            task.add_done_callback(_discard_result)
            raise

    async def _query(self, stmt: Executable) -> Sequence[Sequence[Any]]:
        async with self._db.connect_reader() as conn:
            self.queries += 1
            return list((await conn.execute(stmt)).all())

    def _on_object(self, obj: ObjectRef) -> ColumnElement[bool]:
        return and_(
            visible_at(self._store_id, self._revision),
            TupleRow.object_type == obj.type,
            TupleRow.object_id == obj.id,
        )

    async def _view(self, obj: ObjectRef, subject: SubjectRef) -> _ObjectView:
        key = (obj, subject)
        future = self._objects.get(key)
        if future is None:
            future = asyncio.ensure_future(self._load_view(obj, subject))
            future.add_done_callback(_discard_result)
            self._objects[key] = future
        return await asyncio.shield(future)

    async def _load_view(self, obj: ObjectRef, subject: SubjectRef) -> _ObjectView:
        tuplesets = self._tuplesets.get(obj.type, frozenset())
        conditions: list[ColumnElement[bool]] = [
            TupleRow.subject_relation != "",
            and_(
                TupleRow.subject_type == subject.type,
                TupleRow.subject_id.in_([subject.id, WILDCARD]),
            ),
        ]
        if tuplesets:
            conditions.append(TupleRow.relation.in_(sorted(tuplesets)))
        stmt = select(
            TupleRow.relation, TupleRow.subject_type, TupleRow.subject_id, TupleRow.subject_relation
        ).where(self._on_object(obj), or_(*conditions))
        view: _ObjectView = {}
        for relation, s_type, s_id, s_relation in await self._rows(stmt):
            view.setdefault(relation, []).append(SubjectRef(s_type, s_id, s_relation or None))
        return view

    async def read_subjects(self, obj: ObjectRef, relation: str) -> Sequence[SubjectRef]:
        stmt = select(TupleRow.subject_type, TupleRow.subject_id, TupleRow.subject_relation).where(
            self._on_object(obj), TupleRow.relation == relation
        )
        return [SubjectRef(r[0], r[1], r[2] or None) for r in await self._rows(stmt)]

    async def read_check_candidates(
        self, obj: ObjectRef, relation: str, subject: SubjectRef
    ) -> Sequence[SubjectRef]:
        view = await self._view(obj, subject)
        return [s for s in view.get(relation, ()) if matches_candidate(s, subject)]

    async def read_tupleset(
        self, obj: ObjectRef, tupleset: str, subject: SubjectRef
    ) -> Sequence[SubjectRef]:
        if tupleset not in self._tuplesets.get(obj.type, frozenset()):
            return await self.read_subjects(obj, tupleset)
        return list((await self._view(obj, subject)).get(tupleset, ()))

    async def read_reverse(
        self,
        subject: SubjectRef,
        *,
        object_type: str | None = None,
        relation: str | None = None,
    ) -> Sequence[tuple[ObjectRef, str]]:
        stmt = select(TupleRow.object_type, TupleRow.object_id, TupleRow.relation).where(
            visible_at(self._store_id, self._revision),
            TupleRow.subject_type == subject.type,
            TupleRow.subject_id == subject.id,
            TupleRow.subject_relation == (subject.relation or ""),
        )
        if object_type is not None:
            stmt = stmt.where(TupleRow.object_type == object_type)
        if relation is not None:
            stmt = stmt.where(TupleRow.relation == relation)
        rows = await self._rows(stmt)
        return [(ObjectRef(r[0], r[1]), r[2]) for r in rows]
