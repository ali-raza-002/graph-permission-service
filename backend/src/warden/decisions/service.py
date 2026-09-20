from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from warden.core.errors import NotFoundError
from warden.core.pagination import Page, encode_cursor
from warden.db.tables import DecisionRow
from warden.decisions.repository import DecisionRepository
from warden.decisions.schemas import (
    Decision,
    DecisionKind,
    DecisionStats,
    DecisionSummary,
    TimelineBucket,
)
from warden.engine.trace import TraceNode, count_nodes, prune
from warden.logging import get_logger

log = get_logger(__name__)

_QUEUE_LIMIT = 10_000
_BATCH_SIZE = 500


class DecisionLog:
    """Records every authorization decision.

    In async mode decisions are buffered and flushed in batches by a background task,
    keeping the insert off the check's critical path.
    """

    def __init__(
        self,
        repository: DecisionRepository,
        *,
        mode: Literal["async", "sync", "off"],
        flush_interval_ms: int,
        max_trace_nodes: int,
    ) -> None:
        self._repo = repository
        self._mode = mode
        self._interval = flush_interval_ms / 1000
        self._max_nodes = max_trace_nodes
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_LIMIT)
        self._task: asyncio.Task[None] | None = None
        self.dropped = 0

    async def start(self) -> None:
        if self._mode == "async" and self._task is None:
            self._task = asyncio.create_task(self._run(), name="decision-log-flusher")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self.flush()

    async def record(
        self,
        *,
        decision_id: str,
        store_id: str,
        model_id: str,
        revision: int,
        kind: DecisionKind,
        obj: str,
        relation: str,
        subject: str,
        duration_ms: float,
        allowed: bool | None = None,
        result_count: int | None = None,
        cached: bool = False,
        contextual_tuples: int = 0,
        api_key_id: str | None = None,
        trace: TraceNode | None = None,
    ) -> None:
        if self._mode == "off":
            return
        if trace is not None and count_nodes(trace) > self._max_nodes:
            trace = prune(trace, self._max_nodes)
        row = {
            "id": decision_id,
            "store_id": store_id,
            "model_id": model_id,
            "revision": revision,
            "kind": kind,
            "object": obj,
            "relation": relation,
            "subject": subject,
            "allowed": allowed,
            "result_count": result_count,
            "duration_ms": duration_ms,
            "cached": cached,
            "contextual_tuples": contextual_tuples,
            "api_key_id": api_key_id,
            "trace": trace.model_dump(mode="json", exclude_defaults=True) if trace else None,
            "created_at": datetime.now(UTC),
        }
        if self._mode == "sync":
            await self._repo.insert_many([row])
            return
        try:
            self._queue.put_nowait(row)
        except asyncio.QueueFull:
            self.dropped += 1
            log.warning("decision_log_full", dropped=self.dropped)

    async def flush(self) -> None:
        while not self._queue.empty():
            await self._write(self._drain())

    def _drain(self) -> list[dict[str, Any]]:
        batch: list[dict[str, Any]] = []
        while len(batch) < _BATCH_SIZE:
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return batch

    async def _write(self, batch: list[dict[str, Any]]) -> None:
        try:
            await self._repo.insert_many(batch)
        except Exception as exc:
            log.error("decision_log_write_failed", error=str(exc), batch=len(batch))

    async def _run(self) -> None:
        while True:
            batch = [await self._queue.get()]
            try:
                await asyncio.sleep(self._interval)
            finally:
                batch.extend(self._drain())
                await self._write(batch)


class DecisionService:
    def __init__(self, repository: DecisionRepository) -> None:
        self._repo = repository

    async def page(
        self,
        store_id: str,
        *,
        limit: int,
        cursor: str | None,
        allowed: bool | None = None,
        kind: DecisionKind | None = None,
        subject: str | None = None,
        obj: str | None = None,
    ) -> Page[DecisionSummary]:
        rows = await self._repo.page(
            store_id,
            limit=limit + 1,
            before=cursor,
            allowed=allowed,
            kind=kind,
            subject=subject,
            obj=obj,
        )
        items = [DecisionSummary.model_validate(r) for r in rows[:limit]]
        next_cursor = encode_cursor(items[-1].id) if len(rows) > limit and items else None
        return Page[DecisionSummary](items=items, next_cursor=next_cursor)

    async def get(self, store_id: str, decision_id: str) -> Decision:
        row = await self._repo.get(store_id, decision_id)
        if row is None:
            raise NotFoundError(f"decision '{decision_id}' does not exist")
        return _to_decision(row)

    async def stats(self, store_id: str, *, window_hours: int) -> DecisionStats:
        since = datetime.now(UTC) - timedelta(hours=window_hours)
        raw = await self._repo.stats(store_id, since)
        total = raw["total"]
        decided = raw["allowed"] + raw["denied"]
        return DecisionStats(
            window_hours=window_hours,
            total=total,
            allowed=raw["allowed"],
            denied=raw["denied"],
            list_queries=raw["list_queries"],
            allow_rate=raw["allowed"] / decided if decided else 0.0,
            p50_ms=round(raw["p50"], 3),
            p95_ms=round(raw["p95"], 3),
            cached_rate=raw["cached"] / total if total else 0.0,
            timeline=[TimelineBucket(bucket=b, allowed=a, denied=d) for b, a, d in raw["timeline"]],
        )


def _to_decision(row: DecisionRow) -> Decision:
    summary = DecisionSummary.model_validate(row)
    trace = TraceNode.model_validate(row.trace) if row.trace else None
    return Decision(**summary.model_dump(), trace=trace)
