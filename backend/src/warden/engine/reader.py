from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol

from warden.core.refs import WILDCARD, ObjectRef, RelationTuple, SubjectRef


class TupleReader(Protocol):
    """Snapshot-consistent tuple access used by the evaluator.

    Implementations are bound to a single store and revision, so every read issued
    while resolving one request observes the same immutable set of tuples.
    """

    async def read_subjects(self, obj: ObjectRef, relation: str) -> Sequence[SubjectRef]:
        """All subjects of tuples on obj#relation."""
        ...

    async def read_check_candidates(
        self, obj: ObjectRef, relation: str, subject: SubjectRef
    ) -> Sequence[SubjectRef]:
        """Subjects on obj#relation that could grant access to subject: the exact subject,
        a wildcard of its type, or any userset that needs further resolution."""
        ...

    async def read_tupleset(
        self, obj: ObjectRef, tupleset: str, subject: SubjectRef
    ) -> Sequence[SubjectRef]:
        """All subjects on obj#tupleset while resolving a check for `subject`.

        Same answer as read_subjects; the subject lets a reader fetch everything a check
        needs from one object in a single round trip.
        """
        ...

    async def read_reverse(
        self,
        subject: SubjectRef,
        *,
        object_type: str | None = None,
        relation: str | None = None,
    ) -> Sequence[tuple[ObjectRef, str]]:
        """(object, relation) pairs of tuples whose subject is exactly `subject`."""
        ...


def matches_candidate(stored: SubjectRef, subject: SubjectRef) -> bool:
    if stored == subject or stored.relation is not None:
        return True
    return stored.is_wildcard and stored.type == subject.type and subject.relation is None


class MemoryTupleReader:
    """In-memory reader used by tests, the property suite and contextual tuples."""

    def __init__(self, tuples: Iterable[RelationTuple] = ()) -> None:
        self._forward: dict[tuple[ObjectRef, str], list[SubjectRef]] = {}
        self._reverse: dict[SubjectRef, list[tuple[ObjectRef, str]]] = {}
        for t in tuples:
            self.add(t)

    def add(self, t: RelationTuple) -> None:
        subjects = self._forward.setdefault((t.object, t.relation), [])
        if t.subject not in subjects:
            subjects.append(t.subject)
            self._reverse.setdefault(t.subject, []).append((t.object, t.relation))

    def __len__(self) -> int:
        return sum(len(v) for v in self._forward.values())

    async def read_subjects(self, obj: ObjectRef, relation: str) -> Sequence[SubjectRef]:
        return list(self._forward.get((obj, relation), ()))

    async def read_check_candidates(
        self, obj: ObjectRef, relation: str, subject: SubjectRef
    ) -> Sequence[SubjectRef]:
        return [s for s in self._forward.get((obj, relation), ()) if matches_candidate(s, subject)]

    async def read_tupleset(
        self, obj: ObjectRef, tupleset: str, subject: SubjectRef
    ) -> Sequence[SubjectRef]:
        return await self.read_subjects(obj, tupleset)

    async def read_reverse(
        self,
        subject: SubjectRef,
        *,
        object_type: str | None = None,
        relation: str | None = None,
    ) -> Sequence[tuple[ObjectRef, str]]:
        return [
            (obj, rel)
            for obj, rel in self._reverse.get(subject, ())
            if (object_type is None or obj.type == object_type)
            and (relation is None or rel == relation)
        ]


class ContextualTupleReader:
    """Layers request-scoped contextual tuples over a persistent snapshot reader."""

    def __init__(self, inner: TupleReader, contextual: Iterable[RelationTuple]) -> None:
        self._inner = inner
        self._extra = MemoryTupleReader(contextual)

    async def read_subjects(self, obj: ObjectRef, relation: str) -> Sequence[SubjectRef]:
        return _dedupe(
            await self._inner.read_subjects(obj, relation),
            await self._extra.read_subjects(obj, relation),
        )

    async def read_check_candidates(
        self, obj: ObjectRef, relation: str, subject: SubjectRef
    ) -> Sequence[SubjectRef]:
        return _dedupe(
            await self._inner.read_check_candidates(obj, relation, subject),
            await self._extra.read_check_candidates(obj, relation, subject),
        )

    async def read_tupleset(
        self, obj: ObjectRef, tupleset: str, subject: SubjectRef
    ) -> Sequence[SubjectRef]:
        return _dedupe(
            await self._inner.read_tupleset(obj, tupleset, subject),
            await self._extra.read_subjects(obj, tupleset),
        )

    async def read_reverse(
        self,
        subject: SubjectRef,
        *,
        object_type: str | None = None,
        relation: str | None = None,
    ) -> Sequence[tuple[ObjectRef, str]]:
        return _dedupe(
            await self._inner.read_reverse(subject, object_type=object_type, relation=relation),
            await self._extra.read_reverse(subject, object_type=object_type, relation=relation),
        )


def _dedupe[T](first: Sequence[T], second: Sequence[T]) -> list[T]:
    if not second:
        return list(first)
    seen = set(first)
    return [*first, *(item for item in second if item not in seen)]


def wildcard_of(subject: SubjectRef) -> SubjectRef:
    return SubjectRef(subject.type, WILDCARD)
