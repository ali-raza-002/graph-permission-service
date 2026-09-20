"""The read path: resolve snapshot revision -> cache -> evaluate -> trace -> decision log."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import perf_counter

from warden.auth.keys import Principal
from warden.cache.backends import CheckCache, namespace
from warden.core.consistency import Consistency, encode_token
from warden.core.errors import (
    DeadlineExceededError,
    InvalidTupleError,
    ValidationFailedError,
    WardenError,
)
from warden.core.ids import new_id
from warden.core.refs import ObjectRef, RefParseError, RelationTuple, SubjectRef
from warden.db.database import Database
from warden.decisions.service import DecisionLog
from warden.engine.check import Checker
from warden.engine.expand import Expander
from warden.engine.listing import ObjectLister, UserLister
from warden.engine.reader import ContextualTupleReader, TupleReader
from warden.model.service import ModelService, ResolvedModel
from warden.queries.schemas import (
    BatchCheckRequest,
    BatchCheckResponse,
    BatchCheckResult,
    CheckRequest,
    CheckResponse,
    ExpandRequest,
    ExpandResponse,
    ListObjectsRequest,
    ListObjectsResponse,
    ListUsersRequest,
    ListUsersResponse,
    ResolutionStats,
)
from warden.tuples.repository import PostgresTupleReader
from warden.tuples.revisions import RevisionResolver
from warden.tuples.schemas import TupleKey


@dataclass(frozen=True, slots=True)
class QueryLimits:
    max_depth: int
    max_contextual_tuples: int
    list_max_results: int
    max_batch_checks: int
    list_max_candidates: int = 10_000
    deadline_ms: int = 10_000


@dataclass(slots=True)
class _Snapshot:
    store_id: str
    model: ResolvedModel
    revision: int
    reader: TupleReader
    base: PostgresTupleReader
    contextual: int

    @property
    def token(self) -> str:
        return encode_token(self.store_id, self.revision)


def _elapsed_ms(started: float) -> float:
    return round((perf_counter() - started) * 1000, 3)


class QueryService:
    def __init__(
        self,
        db: Database,
        models: ModelService,
        revisions: RevisionResolver,
        cache: CheckCache,
        decisions: DecisionLog,
        limits: QueryLimits,
    ) -> None:
        self._db = db
        self._models = models
        self._revisions = revisions
        self._cache = cache
        self._decisions = decisions
        self._limits = limits

    @asynccontextmanager
    async def _deadline(self, operation: str) -> AsyncIterator[None]:
        try:
            async with asyncio.timeout(self._limits.deadline_ms / 1000):
                yield
        except TimeoutError:
            raise DeadlineExceededError(
                f"{operation} did not finish within {self._limits.deadline_ms} ms"
            ) from None

    async def _snapshot(
        self,
        store_id: str,
        model_id: str | None,
        consistency: Consistency | None,
        contextual: list[TupleKey] | None = None,
    ) -> _Snapshot:
        contextual = contextual or []
        if len(contextual) > self._limits.max_contextual_tuples:
            raise ValidationFailedError(
                f"at most {self._limits.max_contextual_tuples} contextual tuples are allowed"
            )
        model = await self._models.resolve(store_id, model_id)
        revision = await self._revisions.resolve(store_id, consistency)
        extra = [k.to_tuple() for k in contextual]
        problems = [
            {"tuple": str(t), "reason": p}
            for t in extra
            if (p := model.typesystem.tuple_problem(t)) is not None
        ]
        if problems:
            raise InvalidTupleError("contextual tuples are not valid", details=problems)
        base = PostgresTupleReader(
            self._db, store_id, revision, tuplesets=model.typesystem.tupleset_relations
        )
        reader: TupleReader = ContextualTupleReader(base, extra) if extra else base
        return _Snapshot(store_id, model, revision, reader, base, len(extra))

    def _checker(self, snap: _Snapshot, *, read_cache: bool = True) -> Checker:
        # Contextual tuples change the answer without changing the revision, so those
        # results must stay out of the shared cache.
        use_cache = snap.contextual == 0
        return Checker(
            snap.model.typesystem,
            snap.reader,
            max_depth=self._limits.max_depth,
            cache=self._cache if use_cache else None,
            cache_namespace=namespace(snap.store_id, snap.model.id, snap.revision),
            read_from_cache=read_cache,
        )

    @staticmethod
    def _validate_query(snap: _Snapshot, t: RelationTuple) -> None:
        ts = snap.model.typesystem
        problem = ts.query_problem(t.object.type, t.relation) or ts.subject_problem(t.subject)
        if problem:
            raise InvalidTupleError(problem, details=[{"tuple": str(t), "reason": problem}])

    async def check(
        self, store_id: str, request: CheckRequest, principal: Principal
    ) -> CheckResponse:
        started = perf_counter()
        async with self._deadline("check"):
            snap = await self._snapshot(
                store_id, request.model_id, request.consistency, request.contextual_tuples
            )
            t = request.tuple_key.to_tuple()
            self._validate_query(snap, t)
            checker = self._checker(snap, read_cache=not request.explain)
            outcome = await checker.check(t.object, t.relation, t.subject)
        duration = _elapsed_ms(started)
        decision_id = new_id("dec")
        await self._decisions.record(
            decision_id=decision_id,
            store_id=store_id,
            model_id=snap.model.id,
            revision=snap.revision,
            kind="check",
            obj=str(t.object),
            relation=t.relation,
            subject=str(t.subject),
            allowed=outcome.allowed,
            duration_ms=duration,
            cached=outcome.trace.cached,
            contextual_tuples=snap.contextual,
            api_key_id=principal.key_id,
            trace=outcome.trace,
        )
        return CheckResponse(
            allowed=outcome.allowed,
            decision_id=decision_id,
            model_id=snap.model.id,
            revision=snap.revision,
            consistency_token=snap.token,
            cached=outcome.trace.cached,
            duration_ms=duration,
            trace=outcome.trace,
            stats=ResolutionStats(
                dispatches=checker.stats.dispatches,
                memo_hits=checker.stats.memo_hits,
                cache_hits=checker.stats.cache_hits,
                queries=snap.base.queries,
            ),
        )

    async def batch_check(
        self, store_id: str, request: BatchCheckRequest, principal: Principal
    ) -> BatchCheckResponse:
        if len(request.checks) > self._limits.max_batch_checks:
            raise ValidationFailedError(
                f"a batch may contain at most {self._limits.max_batch_checks} checks"
            )
        started = perf_counter()
        async with self._deadline("batch check"):
            snap = await self._snapshot(
                store_id, request.model_id, request.consistency, request.contextual_tuples
            )
            checker = self._checker(snap)
            results = await asyncio.gather(
                *(
                    self._batch_item(snap, checker, item.tuple_key, item.correlation_id, principal)
                    for item in request.checks
                )
            )
        return BatchCheckResponse(
            results=list(results),
            model_id=snap.model.id,
            revision=snap.revision,
            consistency_token=snap.token,
            duration_ms=_elapsed_ms(started),
        )

    async def _batch_item(
        self,
        snap: _Snapshot,
        checker: Checker,
        key: TupleKey,
        correlation_id: str | None,
        principal: Principal,
    ) -> BatchCheckResult:
        t = key.to_tuple()
        started = perf_counter()
        try:
            self._validate_query(snap, t)
            outcome = await checker.check(t.object, t.relation, t.subject)
        except WardenError as exc:
            return BatchCheckResult(
                correlation_id=correlation_id,
                tuple_key=key,
                allowed=False,
                error=exc.message,
                error_code=exc.code,
            )
        decision_id = new_id("dec")
        await self._decisions.record(
            decision_id=decision_id,
            store_id=snap.store_id,
            model_id=snap.model.id,
            revision=snap.revision,
            kind="check",
            obj=str(t.object),
            relation=t.relation,
            subject=str(t.subject),
            allowed=outcome.allowed,
            duration_ms=_elapsed_ms(started),
            cached=outcome.trace.cached,
            contextual_tuples=snap.contextual,
            api_key_id=principal.key_id,
            trace=outcome.trace,
        )
        return BatchCheckResult(
            correlation_id=correlation_id,
            tuple_key=key,
            allowed=outcome.allowed,
            decision_id=decision_id,
        )

    async def expand(self, store_id: str, request: ExpandRequest) -> ExpandResponse:
        started = perf_counter()
        async with self._deadline("expand"):
            snap = await self._snapshot(store_id, request.model_id, request.consistency)
            problem = snap.model.typesystem.query_problem(
                request.object.split(":", 1)[0], request.relation
            )
            if problem:
                raise InvalidTupleError(problem)
            expander = Expander(
                snap.model.typesystem, snap.reader, max_depth=self._limits.max_depth
            )
            tree = await expander.expand(ObjectRef.parse(request.object), request.relation)
        return ExpandResponse(
            tree=tree,
            model_id=snap.model.id,
            revision=snap.revision,
            consistency_token=snap.token,
            duration_ms=_elapsed_ms(started),
        )

    async def list_objects(
        self, store_id: str, request: ListObjectsRequest, principal: Principal
    ) -> ListObjectsResponse:
        started = perf_counter()
        async with self._deadline("list-objects"):
            snap = await self._snapshot(
                store_id, request.model_id, request.consistency, request.contextual_tuples
            )
            subject = _parse_subject(request.user)
            ts = snap.model.typesystem
            problem = ts.query_problem(request.object_type, request.relation) or ts.subject_problem(
                subject
            )
            if problem:
                raise InvalidTupleError(problem)
            limit = min(
                request.limit or self._limits.list_max_results, self._limits.list_max_results
            )
            lister = ObjectLister(
                ts,
                snap.reader,
                self._checker(snap),
                max_candidates=self._limits.list_max_candidates,
            )
            listing = await lister.find(request.object_type, request.relation, subject, limit=limit)
        objects = listing.items
        duration = _elapsed_ms(started)
        decision_id = new_id("dec")
        await self._decisions.record(
            decision_id=decision_id,
            store_id=store_id,
            model_id=snap.model.id,
            revision=snap.revision,
            kind="list_objects",
            obj=f"{request.object_type}:*",
            relation=request.relation,
            subject=str(subject),
            result_count=len(objects),
            duration_ms=duration,
            contextual_tuples=snap.contextual,
            api_key_id=principal.key_id,
        )
        return ListObjectsResponse(
            objects=[str(o) for o in objects],
            truncated=listing.truncated,
            decision_id=decision_id,
            model_id=snap.model.id,
            revision=snap.revision,
            consistency_token=snap.token,
            duration_ms=duration,
        )

    async def list_users(
        self, store_id: str, request: ListUsersRequest, principal: Principal
    ) -> ListUsersResponse:
        started = perf_counter()
        async with self._deadline("list-users"):
            snap = await self._snapshot(
                store_id, request.model_id, request.consistency, request.contextual_tuples
            )
            obj = ObjectRef.parse(request.object)
            user_type, _, user_relation = request.user_type.partition("#")
            ts = snap.model.typesystem
            problem = ts.query_problem(obj.type, request.relation) or (
                ts.query_problem(user_type, user_relation)
                if user_relation
                else (None if ts.has_type(user_type) else f"type '{user_type}' is not defined")
            )
            if problem:
                raise InvalidTupleError(problem)
            checker = self._checker(snap)
            expander = Expander(ts, snap.reader, max_depth=self._limits.max_depth)
            lister = UserLister(ts, snap.reader, checker, expander)
            listing = await lister.find(
                obj,
                request.relation,
                user_type,
                user_relation or None,
                limit=self._limits.list_max_results,
            )
        users = listing.items
        duration = _elapsed_ms(started)
        decision_id = new_id("dec")
        await self._decisions.record(
            decision_id=decision_id,
            store_id=store_id,
            model_id=snap.model.id,
            revision=snap.revision,
            kind="list_users",
            obj=str(obj),
            relation=request.relation,
            subject=request.user_type,
            result_count=len(users),
            duration_ms=duration,
            contextual_tuples=snap.contextual,
            api_key_id=principal.key_id,
        )
        return ListUsersResponse(
            users=[str(u) for u in users],
            truncated=listing.truncated,
            decision_id=decision_id,
            model_id=snap.model.id,
            revision=snap.revision,
            consistency_token=snap.token,
            duration_ms=duration,
        )


def _parse_subject(raw: str) -> SubjectRef:
    try:
        return SubjectRef.parse(raw)
    except RefParseError as exc:
        raise ValidationFailedError(str(exc)) from None
