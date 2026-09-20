"""Recursive check evaluation over the rewrite AST.

Each distinct sub-problem (object, relation, subject) is resolved at most once per
pass and shared by every branch that needs it, so diamond-shaped and cyclic graphs
cost time linear in the number of sub-problems instead of the number of paths.
Sub-problems run concurrently; unions stop at the first grant and intersections at
the first denial, cancelling sibling work that nobody else is waiting on.

Sharing in-flight work can deadlock on cycles, so the evaluator keeps a wait-for
graph. A request that would close a cycle is answered from an assumption instead
(initially "denied"). If any assumption turns out wrong, the pass is repeated with
the corrected assumptions. That is Kleene iteration from the bottom element, so for
monotone rewrites (everything except the subtracted side of an exclusion) it
converges to the least fixpoint, the same answer a naive bottom-up evaluation gives.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Protocol

from warden.core.errors import ResolutionTooComplexError
from warden.core.refs import ObjectRef, SubjectRef
from warden.dsl.ast import (
    ComputedNode,
    DirectNode,
    ExclusionNode,
    IntersectionNode,
    Rewrite,
    TupleToUsersetNode,
    UnionNode,
)
from warden.dsl.printer import format_rewrite
from warden.dsl.typesystem import TypeSystem, restriction_allows
from warden.engine.reader import TupleReader
from warden.engine.trace import TraceKind, TraceNode, TraceResult, skipped

type CheckKey = tuple[ObjectRef, str, SubjectRef]


class ResultCache(Protocol):
    async def get(self, key: str) -> bool | None: ...

    async def set(self, key: str, value: bool) -> None: ...


@dataclass(slots=True, frozen=True)
class Outcome:
    allowed: bool
    trace: TraceNode
    # True when the result rests on a cycle assumption and is only valid for this pass.
    provisional: bool = False


@dataclass(slots=True)
class CheckStats:
    dispatches: int = 0
    memo_hits: int = 0
    cache_hits: int = 0
    passes: int = 0


@dataclass(slots=True)
class _Flight:
    task: asyncio.Task[Outcome]
    waiters: int = 0


@dataclass(slots=True)
class _Pass:
    assumed: dict[CheckKey, bool]
    short_circuit: bool
    inflight: dict[CheckKey, _Flight] = field(default_factory=dict)
    edges: dict[CheckKey | None, Counter[CheckKey]] = field(default_factory=dict)
    done: dict[CheckKey, Outcome] = field(default_factory=dict)
    cut: set[CheckKey] = field(default_factory=set)
    shown: set[CheckKey] = field(default_factory=set)

    def add_edge(self, source: CheckKey | None, target: CheckKey) -> None:
        self.edges.setdefault(source, Counter())[target] += 1

    def remove_edge(self, source: CheckKey | None, target: CheckKey) -> None:
        counter = self.edges.get(source)
        if counter is None:
            return
        counter[target] -= 1
        if counter[target] <= 0:
            del counter[target]

    def reaches(self, start: CheckKey, goal: CheckKey | None) -> bool:
        if goal is None:
            return False
        stack, seen = [start], {start}
        while stack:
            node = stack.pop()
            if node == goal:
                return True
            for nxt in self.edges.get(node, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return False


def _result(allowed: bool) -> TraceResult:
    return "allowed" if allowed else "denied"


def _label(key: CheckKey) -> str:
    return f"{key[0]}#{key[1]}"


class Checker:
    def __init__(
        self,
        typesystem: TypeSystem,
        reader: TupleReader,
        *,
        max_depth: int = 25,
        max_passes: int = 16,
        cache: ResultCache | None = None,
        cache_namespace: str = "",
        read_from_cache: bool = True,
    ) -> None:
        self._ts = typesystem
        self._reader = reader
        self._max_depth = max_depth
        self._max_passes = max_passes
        self._cache = cache
        self._namespace = cache_namespace
        self._read_cache = read_from_cache
        self._final: dict[CheckKey, Outcome] = {}
        self.stats = CheckStats()

    async def check(self, obj: ObjectRef, relation: str, subject: SubjectRef) -> Outcome:
        root: CheckKey = (obj, relation, subject)
        assumed: dict[CheckKey, bool] = {}
        for attempt in range(self._max_passes):
            self.stats.passes += 1
            # Only the first pass short-circuits. Later passes evaluate every branch so
            # each cycle assumption gets verified against an actual result.
            current = _Pass(assumed=dict(assumed), short_circuit=attempt == 0)
            outcome = await self._resolve(current, root, None, 0)
            if not current.cut:
                return outcome
            unverified = [k for k in current.cut if k not in current.done]
            corrected = {
                k: current.done[k].allowed
                for k in current.cut
                if k in current.done and current.done[k].allowed != assumed.get(k, False)
            }
            if not corrected and not unverified:
                return Outcome(outcome.allowed, outcome.trace)
            assumed.update(corrected)
        raise ResolutionTooComplexError(
            f"resolution of {_label(root)} did not converge after {self._max_passes} passes; "
            "this happens when a cycle passes through the subtracted side of an exclusion"
        )

    def _cache_key(self, key: CheckKey) -> str:
        obj, relation, subject = key
        return f"{self._namespace}{obj}#{relation}@{subject}"

    def _present(self, current: _Pass, key: CheckKey, outcome: Outcome) -> Outcome:
        """Full trace the first time a result is used in a pass, a reference after that."""
        if key in current.shown:
            ref = outcome.trace.model_copy(update={"memoized": True, "children": []})
            return Outcome(outcome.allowed, ref, outcome.provisional)
        current.shown.add(key)
        return outcome

    async def _resolve(
        self, current: _Pass, key: CheckKey, parent: CheckKey | None, depth: int
    ) -> Outcome:
        obj, relation, subject = key
        if subject.relation == relation and subject.as_object() == obj:
            leaf = TraceNode(
                kind="tuple", label=f"{subject} is the userset itself", result="allowed"
            )
            trace = TraceNode(
                kind="check",
                label=_label(key),
                result="allowed",
                object=str(obj),
                relation=relation,
                children=[leaf],
            )
            return Outcome(True, trace)

        final = self._final.get(key)
        if final is not None:
            self.stats.memo_hits += 1
            return self._present(current, key, final)
        finished = current.done.get(key)
        if finished is not None:
            self.stats.memo_hits += 1
            return self._present(current, key, finished)

        flight = current.inflight.get(key)
        joining = flight is not None
        if flight is None:
            if depth >= self._max_depth:
                raise ResolutionTooComplexError(
                    f"resolution exceeded the maximum depth of {self._max_depth} at {_label(key)}"
                )
            cached = await self._from_cache(key)
            if cached is not None:
                return cached
            # Another branch may have started or finished this key while we awaited the cache.
            if (finished := current.done.get(key)) is not None:
                return self._present(current, key, finished)
            flight = current.inflight.get(key)
            joining = flight is not None
            if flight is None:
                flight = _Flight(asyncio.ensure_future(self._evaluate(current, key, depth)))
                current.inflight[key] = flight

        if joining and current.reaches(key, parent):
            current.cut.add(key)
            assumption = current.assumed.get(key, False)
            trace = TraceNode(
                kind="cycle",
                label=_label(key),
                result=_result(assumption),
                object=str(obj),
                relation=relation,
            )
            return Outcome(assumption, trace, provisional=True)

        current.add_edge(parent, key)
        flight.waiters += 1
        try:
            outcome = await asyncio.shield(flight.task)
        finally:
            current.remove_edge(parent, key)
            flight.waiters -= 1
            if flight.waiters == 0 and not flight.task.done():
                flight.task.cancel()
                current.inflight.pop(key, None)
        return self._present(current, key, outcome)

    async def _from_cache(self, key: CheckKey) -> Outcome | None:
        if self._cache is None or not self._read_cache:
            return None
        hit = await self._cache.get(self._cache_key(key))
        if hit is None:
            return None
        self.stats.cache_hits += 1
        obj, relation, _ = key
        trace = TraceNode(
            kind="check",
            label=_label(key),
            result=_result(hit),
            object=str(obj),
            relation=relation,
            cached=True,
        )
        return Outcome(hit, trace)

    async def _evaluate(self, current: _Pass, key: CheckKey, depth: int) -> Outcome:
        obj, relation, _ = key
        self.stats.dispatches += 1
        started = perf_counter()
        if self._ts.has_relation(obj.type, relation):
            rewrite = self._ts.relation(obj.type, relation).rewrite
            inner = await self._eval(current, rewrite, key, depth + 1)
            children = [inner.trace]
        else:
            inner = Outcome(False, TraceNode(kind="check", label=_label(key), result="denied"))
            children = []
        trace = TraceNode(
            kind="check",
            label=_label(key),
            result=_result(inner.allowed),
            object=str(obj),
            relation=relation,
            duration_ms=round((perf_counter() - started) * 1000, 3),
            children=children,
        )
        outcome = Outcome(inner.allowed, trace, inner.provisional)
        current.done[key] = outcome
        current.inflight.pop(key, None)
        if not outcome.provisional:
            self._final[key] = outcome
            if self._cache is not None:
                await self._cache.set(self._cache_key(key), outcome.allowed)
        return outcome

    async def _eval(self, current: _Pass, node: Rewrite, key: CheckKey, depth: int) -> Outcome:
        obj, _, subject = key
        match node:
            case DirectNode():
                return await self._direct(current, node, key, depth)
            case ComputedNode(relation=target):
                sub = await self._resolve(current, (obj, target, subject), key, depth)
                trace = TraceNode(
                    kind="computed",
                    label=target,
                    result=sub.trace.result,
                    relation=target,
                    children=[sub.trace],
                )
                return Outcome(sub.allowed, trace, sub.provisional)
            case TupleToUsersetNode():
                return await self._tuple_to_userset(current, node, key, depth)
            case UnionNode(children=children):
                return await self._combine(
                    current,
                    "union",
                    "or",
                    [self._eval(current, c, key, depth) for c in children],
                    [format_rewrite(c) for c in children],
                    stop=lambda _i, r: r.allowed,
                    stopped_allowed=True,
                    combine=lambda rs: any(r.allowed for r in rs),
                )
            case IntersectionNode(children=children):
                return await self._combine(
                    current,
                    "intersection",
                    "and",
                    [self._eval(current, c, key, depth) for c in children],
                    [format_rewrite(c) for c in children],
                    stop=lambda _i, r: not r.allowed,
                    stopped_allowed=False,
                    combine=lambda rs: all(r.allowed for r in rs),
                )
            case ExclusionNode(base=base, subtract=subtract):
                return await self._combine(
                    current,
                    "exclusion",
                    "but not",
                    [
                        self._eval(current, base, key, depth),
                        self._eval(current, subtract, key, depth),
                    ],
                    [format_rewrite(base), format_rewrite(subtract)],
                    stop=lambda i, r: r.allowed if i == 1 else not r.allowed,
                    stopped_allowed=False,
                    combine=lambda rs: rs[0].allowed and not rs[1].allowed,
                )

    async def _direct(self, current: _Pass, node: DirectNode, key: CheckKey, depth: int) -> Outcome:
        obj, relation, subject = key
        label = format_rewrite(node)
        candidates = [
            s
            for s in await self._reader.read_check_candidates(obj, relation, subject)
            if any(restriction_allows(r, s) for r in node.types)
        ]
        for stored in candidates:
            wildcard_hit = (
                stored.is_wildcard and stored.type == subject.type and subject.relation is None
            )
            if stored == subject or wildcard_hit:
                tuple_key = f"{obj}#{relation}@{stored}"
                leaf = TraceNode(
                    kind="tuple", label=tuple_key, result="allowed", tuple_key=tuple_key
                )
                return Outcome(
                    True, TraceNode(kind="direct", label=label, result="allowed", children=[leaf])
                )

        usersets = [(s, s.relation) for s in candidates if s.relation is not None]
        labels = [f"{obj}#{relation}@{s}" for s, _ in usersets]
        return await self._combine(
            current,
            "direct",
            label,
            [
                self._through_tuple(current, tuple_key, (s.as_object(), rel, subject), key, depth)
                for tuple_key, (s, rel) in zip(labels, usersets, strict=True)
            ],
            labels,
            stop=lambda _i, r: r.allowed,
            stopped_allowed=True,
            combine=lambda rs: any(r.allowed for r in rs),
        )

    async def _tuple_to_userset(
        self, current: _Pass, node: TupleToUsersetNode, key: CheckKey, depth: int
    ) -> Outcome:
        obj, _, subject = key
        allowed_parents = self._ts.direct_restrictions(obj.type, node.tupleset)
        parents = [
            p
            for p in await self._reader.read_tupleset(obj, node.tupleset, subject)
            if p.relation is None
            and not p.is_wildcard
            and any(restriction_allows(r, p) for r in allowed_parents)
            and self._ts.has_relation(p.type, node.computed)
        ]
        labels = [f"{obj}#{node.tupleset}@{p}" for p in parents]
        return await self._combine(
            current,
            "tuple_to_userset",
            format_rewrite(node),
            [
                self._through_tuple(
                    current, tuple_key, (p.as_object(), node.computed, subject), key, depth
                )
                for tuple_key, p in zip(labels, parents, strict=True)
            ],
            labels,
            stop=lambda _i, r: r.allowed,
            stopped_allowed=True,
            combine=lambda rs: any(r.allowed for r in rs),
        )

    async def _through_tuple(
        self, current: _Pass, tuple_key: str, target: CheckKey, parent: CheckKey, depth: int
    ) -> Outcome:
        outcome = await self._resolve(current, target, parent, depth)
        trace = TraceNode(
            kind="tuple",
            label=tuple_key,
            result=outcome.trace.result,
            tuple_key=tuple_key,
            children=[outcome.trace],
        )
        return Outcome(outcome.allowed, trace, outcome.provisional)

    @staticmethod
    async def _combine(
        current: _Pass,
        kind: TraceKind,
        label: str,
        coros: list[Coroutine[Any, Any, Outcome]],
        child_labels: list[str],
        *,
        stop: Callable[[int, Outcome], bool],
        stopped_allowed: bool,
        combine: Callable[[list[Outcome]], bool],
    ) -> Outcome:
        if current.short_circuit:
            results, stopper = await race(coros, stop)
        else:
            gathered = await _all(coros)
            results = list(gathered)
            stopper = next((i for i, r in enumerate(gathered) if stop(i, r)), None)

        if stopper is not None:
            decisive = results[stopper]
            assert decisive is not None
            allowed, provisional = stopped_allowed, decisive.provisional
        else:
            completed = [r for r in results if r is not None]
            allowed = combine(completed) if completed else False
            provisional = any(r.provisional for r in completed)

        children: list[TraceNode] = []
        for index, result in enumerate(results):
            child = result.trace if result is not None else skipped(child_labels[index])
            if kind == "exclusion":
                child = child.model_copy(update={"role": "base" if index == 0 else "subtract"})
            children.append(child)
        trace = TraceNode(kind=kind, label=label, result=_result(allowed), children=children)
        return Outcome(allowed, trace, provisional)


async def _all(coros: list[Coroutine[Any, Any, Outcome]]) -> list[Outcome]:
    """Run every sub-problem; if one fails, cancel the rest and raise its error."""
    try:
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(c) for c in coros]
    except ExceptionGroup as failed:
        raise failed.exceptions[0] from None
    return [t.result() for t in tasks]


async def race(
    coros: list[Coroutine[Any, Any, Outcome]], stop: Callable[[int, Outcome], bool]
) -> tuple[list[Outcome | None], int | None]:
    """Run sub-problems concurrently, cancelling the rest once `stop` holds for one.

    Returns per-child results (None for cancelled children) and the index of the child
    that stopped the race, if any.
    """
    if not coros:
        return [], None
    if len(coros) == 1:
        only = await coros[0]
        return [only], 0 if stop(0, only) else None

    tasks: list[asyncio.Future[Outcome]] = [asyncio.ensure_future(c) for c in coros]
    index_of = {task: i for i, task in enumerate(tasks)}
    stopper: int | None = None
    try:
        pending: set[asyncio.Future[Outcome]] = set(tasks)
        while pending and stopper is None:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in sorted(done, key=lambda t: index_of[t]):
                if stop(index_of[task], task.result()):
                    stopper = index_of[task]
                    break
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    results: list[Outcome | None] = [
        t.result() if t.done() and not t.cancelled() and t.exception() is None else None
        for t in tasks
    ]
    return results, stopper
