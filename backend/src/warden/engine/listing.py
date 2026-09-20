"""ListObjects and ListUsers.

ListObjects walks the relationship graph backwards from the subject: starting at the
tuples that name the subject, it follows computed-userset, userset and
tuple-to-userset edges until it reaches usersets of the requested type and relation.
That yields a candidate superset (intersections and exclusions are not decided by a
reverse walk), so each candidate is confirmed with a regular check that shares one
memo table across the whole request.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from warden.core.refs import ObjectRef, SubjectRef
from warden.dsl.typesystem import TypeSystem
from warden.engine.check import Checker
from warden.engine.expand import Expander, collect_subjects
from warden.engine.reader import TupleReader, wildcard_of

type Userset = tuple[ObjectRef, str]


@dataclass(frozen=True, slots=True)
class Listing[T]:
    items: list[T]
    # More results may exist: the limit was reached or the candidate cap cut the walk short.
    truncated: bool


class ObjectLister:
    def __init__(
        self,
        typesystem: TypeSystem,
        reader: TupleReader,
        checker: Checker,
        *,
        max_candidates: int = 10_000,
        concurrency: int = 32,
    ) -> None:
        self._ts = typesystem
        self._reader = reader
        self._checker = checker
        self._max_candidates = max_candidates
        self._concurrency = concurrency
        self._semaphore = asyncio.Semaphore(concurrency)

    async def list_objects(
        self, object_type: str, relation: str, subject: SubjectRef, *, limit: int | None = None
    ) -> list[ObjectRef]:
        return (await self.find(object_type, relation, subject, limit=limit)).items

    async def find(
        self, object_type: str, relation: str, subject: SubjectRef, *, limit: int | None = None
    ) -> Listing[ObjectRef]:
        """Objects the subject holds `relation` on, in id order.

        Candidates are confirmed one bounded wave at a time, so a small limit over a
        large candidate set stops after a few waves instead of checking everything.
        """
        candidates, capped = await self._candidates(object_type, relation, subject)
        candidates.sort(key=lambda o: o.id)
        allowed: list[ObjectRef] = []
        for start in range(0, len(candidates), self._concurrency):
            wave = candidates[start : start + self._concurrency]
            verdicts = await asyncio.gather(*(self._confirm(c, relation, subject) for c in wave))
            allowed.extend(c for c, ok in zip(wave, verdicts, strict=True) if ok)
            if limit is not None and len(allowed) >= limit:
                more = len(allowed) > limit or start + len(wave) < len(candidates)
                return Listing(allowed[:limit], truncated=more or capped)
        return Listing(allowed, truncated=capped)

    async def candidates(
        self, object_type: str, relation: str, subject: SubjectRef
    ) -> list[ObjectRef]:
        return (await self._candidates(object_type, relation, subject))[0]

    async def _candidates(
        self, object_type: str, relation: str, subject: SubjectRef
    ) -> tuple[list[ObjectRef], bool]:
        seeds: list[Userset] = []
        if subject.relation is not None:
            seeds.append((subject.as_object(), subject.relation))
        seeds.extend(await self._reader.read_reverse(subject))
        if subject.relation is None and not subject.is_wildcard:
            seeds.extend(await self._reader.read_reverse(wildcard_of(subject)))

        seen: set[Userset] = set(seeds)
        frontier: list[Userset] = list(seen)
        found: dict[ObjectRef, None] = {}
        while frontier and len(found) < self._max_candidates:
            for obj, rel in frontier:
                if obj.type == object_type and rel == relation:
                    found[obj] = None
            neighbours = await asyncio.gather(*(self._step(obj, rel) for obj, rel in frontier))
            frontier = []
            for batch in neighbours:
                for userset in batch:
                    if userset not in seen:
                        seen.add(userset)
                        frontier.append(userset)
        capped = len(found) >= self._max_candidates
        return list(found)[: self._max_candidates], capped

    async def _step(self, obj: ObjectRef, relation: str) -> list[Userset]:
        """Usersets that `obj#relation` directly contributes to."""
        out: list[Userset] = [(obj, r) for r in self._ts.computed_dependents(obj.type, relation)]
        async with self._semaphore:
            if self._ts.is_userset_target(obj.type, relation):
                out.extend(await self._reader.read_reverse(SubjectRef(obj.type, obj.id, relation)))
            for edge in self._ts.ttu_dependents(obj.type, relation):
                parents_of: Sequence[tuple[ObjectRef, str]] = await self._reader.read_reverse(
                    SubjectRef(obj.type, obj.id),
                    object_type=edge.object_type,
                    relation=edge.tupleset,
                )
                out.extend((child, edge.relation) for child, _ in parents_of)
        return out

    async def _confirm(self, obj: ObjectRef, relation: str, subject: SubjectRef) -> bool:
        async with self._semaphore:
            return (await self._checker.check(obj, relation, subject)).allowed


class UserLister:
    def __init__(
        self,
        typesystem: TypeSystem,
        reader: TupleReader,
        checker: Checker,
        expander: Expander,
        *,
        concurrency: int = 32,
    ) -> None:
        self._ts = typesystem
        self._reader = reader
        self._checker = checker
        self._expander = expander
        self._semaphore = asyncio.Semaphore(concurrency)

    async def list_users(
        self, obj: ObjectRef, relation: str, user_type: str, user_relation: str | None = None
    ) -> list[SubjectRef]:
        tree = await self._expander.expand(obj, relation)
        candidates = sorted(
            (
                s
                for s in collect_subjects(tree)
                if s.type == user_type and s.relation == user_relation
            ),
            key=str,
        )

        async def confirm(subject: SubjectRef) -> bool:
            async with self._semaphore:
                return (await self._checker.check(obj, relation, subject)).allowed

        verdicts = await asyncio.gather(*(confirm(s) for s in candidates))
        return [s for s, ok in zip(candidates, verdicts, strict=True) if ok]

    async def find(
        self,
        obj: ObjectRef,
        relation: str,
        user_type: str,
        user_relation: str | None = None,
        *,
        limit: int,
    ) -> Listing[SubjectRef]:
        users = await self.list_users(obj, relation, user_type, user_relation)
        return Listing(users[:limit], truncated=len(users) > limit)
