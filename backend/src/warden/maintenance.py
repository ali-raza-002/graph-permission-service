"""Garbage collection of tuple history, old decisions and deleted stores.

Snapshot reads need deleted tuples to linger, but only for as long as a consistency
token may still ask for them. Each run turns the retention window into a per-store
revision horizon (the newest revision committed before the window began), raises
`stores.gc_revision` to it, and drops every tuple deleted at or before it: such a
tuple is invisible at the horizon and at every later revision, so no readable
snapshot can observe it. Tokens older than the horizon fail with snapshot_too_old.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update

from warden.db.database import Database
from warden.db.tables import RevisionRow, StoreRow, TupleRow
from warden.decisions.repository import DecisionRepository
from warden.logging import get_logger

log = get_logger(__name__)

# Any constant works; it only has to be the same for every replica.
_GC_LOCK_ID = 0x5741_5244


@dataclass(frozen=True, slots=True)
class GcReport:
    stores_advanced: int = 0
    tuples_removed: int = 0
    revisions_removed: int = 0
    decisions_removed: int = 0
    stores_purged: int = 0
    skipped: bool = False


class GarbageCollector:
    def __init__(
        self,
        db: Database,
        decisions: DecisionRepository,
        *,
        history_retention: timedelta,
        decision_retention: timedelta,
        interval_seconds: float,
    ) -> None:
        self._db = db
        self._decisions = decisions
        self._history = history_retention
        self._decision_retention = decision_retention
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="warden-gc")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                report = await self.run_once()
            except Exception as exc:
                log.error("gc_failed", error=str(exc))
            else:
                if not report.skipped:
                    log.info("gc_completed", **asdict(report))

    async def run_once(self, *, now: datetime | None = None) -> GcReport:
        now = now or datetime.now(UTC)
        cutoff = now - self._history
        async with self._db.transaction() as session:
            # One replica collects at a time; the others skip this round.
            locked = await session.scalar(select(func.pg_try_advisory_xact_lock(_GC_LOCK_ID)))
            if not locked:
                return GcReport(skipped=True)

            horizons = (
                select(RevisionRow.store_id, func.max(RevisionRow.revision).label("horizon"))
                .where(RevisionRow.committed_at < cutoff)
                .group_by(RevisionRow.store_id)
                .subquery()
            )
            advanced = (
                await session.execute(
                    update(StoreRow)
                    .where(StoreRow.id == horizons.c.store_id)
                    .where(StoreRow.gc_revision < horizons.c.horizon)
                    .values(gc_revision=horizons.c.horizon)
                    .returning(StoreRow.id, StoreRow.gc_revision)
                )
            ).all()

            tuples_removed = revisions_removed = 0
            for store_id, horizon in advanced:
                removed = await session.execute(
                    delete(TupleRow).where(
                        TupleRow.store_id == store_id,
                        TupleRow.deleted_revision.is_not(None),
                        TupleRow.deleted_revision <= horizon,
                    )
                )
                tuples_removed += int(getattr(removed, "rowcount", 0) or 0)
                pruned = await session.execute(
                    delete(RevisionRow).where(
                        RevisionRow.store_id == store_id, RevisionRow.revision < horizon
                    )
                )
                revisions_removed += int(getattr(pruned, "rowcount", 0) or 0)

            purged = await session.execute(delete(StoreRow).where(StoreRow.deleted_at < cutoff))

        decisions_removed = await self._decisions.purge(now - self._decision_retention)
        return GcReport(
            stores_advanced=len(advanced),
            tuples_removed=tuples_removed,
            revisions_removed=revisions_removed,
            decisions_removed=decisions_removed,
            stores_purged=int(getattr(purged, "rowcount", 0) or 0),
        )
