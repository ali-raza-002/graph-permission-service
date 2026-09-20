from __future__ import annotations

from collections import Counter

from warden.core.consistency import Consistency, encode_token
from warden.core.errors import InvalidTupleError, ValidationFailedError
from warden.core.pagination import InvalidCursorError, Page, decode_str_cursor, encode_cursor
from warden.core.refs import RefParseError, SubjectRef
from warden.model.service import ModelService
from warden.tuples.repository import TupleRepository
from warden.tuples.revisions import RevisionResolver
from warden.tuples.schemas import (
    StoredTuple,
    TupleChange,
    TupleFilter,
    TupleKey,
    WriteCommand,
    WriteResult,
)


class TuplePage(Page[StoredTuple]):
    revision: int


class TupleService:
    def __init__(
        self,
        tuples: TupleRepository,
        models: ModelService,
        revisions: RevisionResolver,
        *,
        max_tuples_per_write: int,
    ) -> None:
        self._tuples = tuples
        self._models = models
        self._revisions = revisions
        self._max_per_write = max_tuples_per_write

    async def write(self, store_id: str, command: WriteCommand) -> WriteResult:
        total = len(command.writes) + len(command.deletes)
        if total == 0:
            raise ValidationFailedError("a write must contain at least one write or delete")
        if total > self._max_per_write:
            raise ValidationFailedError(
                f"a write may contain at most {self._max_per_write} tuples, got {total}"
            )
        writes = [k.to_tuple() for k in command.writes]
        deletes = [k.to_tuple() for k in command.deletes]

        repeated = [t for t, n in Counter([*writes, *deletes]).items() if n > 1]
        if repeated:
            raise ValidationFailedError(
                "each tuple may appear only once across writes and deletes",
                details=[{"tuple": str(t)} for t in repeated],
            )

        resolved = await self._models.resolve(store_id, command.model_id)
        problems = [
            {"tuple": str(t), "reason": problem}
            for t in writes
            if (problem := resolved.typesystem.tuple_problem(t)) is not None
        ]
        if problems:
            raise InvalidTupleError(
                f"{len(problems)} tuple(s) are not valid under model {resolved.id}",
                details=problems,
            )

        outcome = await self._tuples.write(
            store_id,
            writes=writes,
            deletes=deletes,
            preconditions=[(p.tuple_key.to_tuple(), p.must_exist) for p in command.preconditions],
            on_duplicate=command.on_duplicate,
            on_missing=command.on_missing,
        )
        self._revisions.observe(store_id, outcome.revision)
        return WriteResult(
            revision=outcome.revision,
            consistency_token=encode_token(store_id, outcome.revision),
            model_id=resolved.id,
            written=outcome.written,
            deleted=outcome.deleted,
        )

    async def read(
        self,
        store_id: str,
        tuple_filter: TupleFilter,
        *,
        consistency: Consistency | None,
        limit: int,
        cursor: str | None,
    ) -> TuplePage:
        """Read one page of live tuples.

        The first page resolves a snapshot from `consistency`; its cursor carries that
        revision, so every later page reads the same snapshot and the listing never
        mixes tuples from different revisions.
        """
        subject = None
        if tuple_filter.user:
            try:
                subject = SubjectRef.parse(tuple_filter.user)
            except RefParseError as exc:
                raise ValidationFailedError(str(exc)) from None
        position = _decode_pair_cursor(cursor)
        if position is None:
            revision, after_id = await self._revisions.resolve(store_id, consistency), None
        else:
            revision, after_id = await self._revisions.exact(store_id, position[0]), position[1]
        records = await self._tuples.read(
            store_id,
            revision,
            object_type=tuple_filter.object_type,
            object_id=tuple_filter.object_id,
            relation=tuple_filter.relation,
            subject=subject,
            limit=limit + 1,
            after_id=after_id,
        )
        items = [
            StoredTuple(
                id=r.id,
                object=str(r.tuple.object),
                relation=r.tuple.relation,
                user=str(r.tuple.subject),
                created_revision=r.created_revision,
                created_at=r.created_at,
            )
            for r in records[:limit]
        ]
        next_cursor = (
            encode_cursor(f"{revision}.{items[-1].id}") if len(records) > limit and items else None
        )
        return TuplePage(items=items, next_cursor=next_cursor, revision=revision)

    async def changes(self, store_id: str, *, limit: int, cursor: str | None) -> Page[TupleChange]:
        before = _decode_pair_cursor(cursor)
        records = await self._tuples.changes(store_id, limit=limit + 1, before=before)
        items = [
            TupleChange(
                operation=r.operation, revision=r.revision, tuple_key=TupleKey.from_tuple(r.tuple)
            )
            for r in records[:limit]
        ]
        next_cursor = None
        if len(records) > limit and records:
            last = records[limit - 1]
            next_cursor = encode_cursor(f"{last.revision}.{last.id}")
        return Page[TupleChange](items=items, next_cursor=next_cursor)

    async def counts(self, store_id: str) -> dict[str, int]:
        return await self._tuples.count_live(store_id)


def _decode_pair_cursor(cursor: str | None) -> tuple[int, int] | None:
    raw = decode_str_cursor(cursor)
    if raw is None:
        return None
    revision, _, row_id = raw.partition(".")
    try:
        return int(revision), int(row_id)
    except ValueError:
        raise InvalidCursorError("cursor is malformed") from None
