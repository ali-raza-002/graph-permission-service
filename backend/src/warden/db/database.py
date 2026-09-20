from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    def __init__(
        self,
        url: str,
        *,
        pool_size: int = 20,
        max_overflow: int = 10,
        pool_timeout: float = 5.0,
        max_concurrent_reads: int | None = None,
        echo: bool = False,
    ) -> None:
        self.engine: AsyncEngine = create_async_engine(
            url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            # Pre-ping would add a round trip to every checkout on the check path; stale
            # connections are recycled on a timer instead.
            pool_recycle=300,
            echo=echo,
        )
        # Snapshot reads fan out widely during a check. Capping them below the pool size
        # for the whole process leaves connections for writes and key lookups, so a burst
        # of list-objects calls queues here instead of timing out in the pool.
        capacity = pool_size + max_overflow
        reads = max_concurrent_reads or capacity
        self._read_slots = asyncio.Semaphore(max(1, min(reads, capacity - 2)))
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        # Snapshot reads filter on revision and never write, so they skip BEGIN/ROLLBACK
        # and save two round trips per query.
        self.reader: AsyncEngine = self.engine.execution_options(isolation_level="AUTOCOMMIT")

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        async with self.sessions() as session, session.begin():
            yield session

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessions() as session:
            yield session

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[AsyncConnection]:
        async with self.engine.connect() as conn:
            yield conn

    @asynccontextmanager
    async def connect_reader(self) -> AsyncIterator[AsyncConnection]:
        async with self._read_slots, self.reader.connect() as conn:
            yield conn

    async def ping(self) -> bool:
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    async def dispose(self) -> None:
        await self.engine.dispose()
