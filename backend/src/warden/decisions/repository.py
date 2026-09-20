from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Integer, case, cast, delete, func, insert, select

from warden.db.database import Database
from warden.db.tables import DecisionRow


class DecisionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def insert_many(self, rows: Sequence[dict[str, Any]]) -> None:
        if not rows:
            return
        async with self._db.transaction() as session:
            await session.execute(insert(DecisionRow), list(rows))

    async def page(
        self,
        store_id: str,
        *,
        limit: int,
        before: str | None = None,
        allowed: bool | None = None,
        kind: str | None = None,
        subject: str | None = None,
        obj: str | None = None,
    ) -> Sequence[DecisionRow]:
        stmt = select(DecisionRow).where(DecisionRow.store_id == store_id)
        if before is not None:
            stmt = stmt.where(DecisionRow.id < before)
        if allowed is not None:
            stmt = stmt.where(DecisionRow.allowed.is_(allowed))
        if kind is not None:
            stmt = stmt.where(DecisionRow.kind == kind)
        if subject:
            stmt = stmt.where(DecisionRow.subject == subject)
        if obj:
            stmt = stmt.where(DecisionRow.object == obj)
        stmt = stmt.order_by(DecisionRow.id.desc()).limit(limit)
        async with self._db.session() as session:
            return (await session.scalars(stmt)).all()

    async def get(self, store_id: str, decision_id: str) -> DecisionRow | None:
        stmt = select(DecisionRow).where(
            DecisionRow.store_id == store_id, DecisionRow.id == decision_id
        )
        async with self._db.session() as session:
            return (await session.scalars(stmt)).one_or_none()

    async def stats(self, store_id: str, since: datetime) -> dict[str, Any]:
        """Check statistics for the window. List queries have no allow/deny verdict and
        very different latencies, so they are counted separately."""
        window = (DecisionRow.store_id == store_id, DecisionRow.created_at >= since)
        scope = (*window, DecisionRow.kind == "check")
        lists = select(func.count()).where(*window, DecisionRow.kind != "check")
        totals = select(
            func.count(),
            func.coalesce(func.sum(cast(DecisionRow.allowed.is_(True), Integer)), 0),
            func.coalesce(func.sum(cast(DecisionRow.allowed.is_(False), Integer)), 0),
            func.coalesce(func.sum(cast(DecisionRow.cached, Integer)), 0),
            func.coalesce(
                func.percentile_cont(0.5).within_group(DecisionRow.duration_ms.asc()), 0.0
            ),
            func.coalesce(
                func.percentile_cont(0.95).within_group(DecisionRow.duration_ms.asc()), 0.0
            ),
        ).where(*scope)
        bucket = func.date_trunc("hour", DecisionRow.created_at).label("bucket")
        timeline = (
            select(
                bucket,
                func.sum(case((DecisionRow.allowed.is_(True), 1), else_=0)),
                func.sum(case((DecisionRow.allowed.is_(False), 1), else_=0)),
            )
            .where(*scope)
            .group_by(bucket)
            .order_by(bucket)
        )
        async with self._db.connect() as conn:
            total_row = (await conn.execute(totals)).one()
            buckets = (await conn.execute(timeline)).all()
            list_queries = int((await conn.execute(lists)).scalar_one())
        return {
            "list_queries": list_queries,
            "total": int(total_row[0]),
            "allowed": int(total_row[1]),
            "denied": int(total_row[2]),
            "cached": int(total_row[3]),
            "p50": float(total_row[4]),
            "p95": float(total_row[5]),
            "timeline": [(b[0], int(b[1]), int(b[2])) for b in buckets],
        }

    async def purge(self, before: datetime, *, batch_size: int = 5_000) -> int:
        """Delete decisions older than `before` in batches, keeping each lock short."""
        removed = 0
        while True:
            doomed = select(DecisionRow.id).where(DecisionRow.created_at < before).limit(batch_size)
            async with self._db.transaction() as session:
                result = await session.execute(
                    delete(DecisionRow).where(DecisionRow.id.in_(doomed))
                )
            count = int(getattr(result, "rowcount", 0) or 0)
            removed += count
            if count < batch_size:
                return removed
