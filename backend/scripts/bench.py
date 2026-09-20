"""Benchmark check and list-objects latency against a synthetic organisation.

Builds nested groups, a folder hierarchy and documents in a fresh store, then measures
the full read path (snapshot resolution, cache, evaluation, Postgres reads) in process,
first with the cache cold and then warm.

    python backend/scripts/bench.py --users 2000 --documents 10000 --checks 2000
"""

from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import delete

from warden.auth.keys import Principal, Scope
from warden.config import Settings
from warden.container import Container
from warden.core.refs import RelationTuple
from warden.db.tables import StoreRow
from warden.queries.schemas import CheckRequest, ListObjectsRequest
from warden.tuples.schemas import TupleKey, WriteCommand

MODEL = """model
  schema 1.1

type user

type group
  relations
    define member: [user, group#member]

type folder
  relations
    define parent: [folder]
    define editor: [user, group#member] or editor from parent
    define viewer: [user, group#member] or editor or viewer from parent

type document
  relations
    define parent: [folder]
    define owner: [user]
    define editor: [user, group#member] or owner or editor from parent
    define viewer: [user, group#member] or editor or viewer from parent
"""

PRINCIPAL = Principal(key_id=None, name="bench", scopes=frozenset(Scope), store_id=None)


@dataclass(frozen=True)
class Sizes:
    users: int
    groups: int
    folders: int
    documents: int


def build_tuples(sizes: Sizes, rng: random.Random) -> tuple[list[str], dict[int, int]]:
    """Synthetic relationships plus the owner of every document."""
    tuples: list[str] = ["folder:f0#viewer@group:g0#member"]
    owners: dict[int, int] = {}
    for g in range(sizes.groups):
        for u in rng.sample(range(sizes.users), k=min(12, sizes.users)):
            tuples.append(f"group:g{g}#member@user:u{u}")
        if g > 0 and rng.random() < 0.3:
            tuples.append(f"group:g{rng.randrange(g)}#member@group:g{g}#member")
    for f in range(1, sizes.folders):
        tuples.append(f"folder:f{f}#parent@folder:f{rng.randrange(f // 3, f)}")
    for f in rng.sample(range(sizes.folders), k=max(1, sizes.folders // 10)):
        relation = rng.choice(["viewer", "editor"])
        tuples.append(f"folder:f{f}#{relation}@group:g{rng.randrange(sizes.groups)}#member")
    for d in range(sizes.documents):
        tuples.append(f"document:d{d}#parent@folder:f{rng.randrange(sizes.folders)}")
        owners[d] = rng.randrange(sizes.users)
        tuples.append(f"document:d{d}#owner@user:u{owners[d]}")
        if rng.random() < 0.2:
            tuples.append(f"document:d{d}#viewer@user:u{rng.randrange(sizes.users)}")
    return list(dict.fromkeys(tuples)), owners


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))
    return ordered[index]


async def timed(
    calls: list[Callable[[], Awaitable[bool]]], concurrency: int
) -> tuple[list[float], float, int]:
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    allowed = 0

    async def run(call: Callable[[], Awaitable[bool]]) -> None:
        nonlocal allowed
        async with semaphore:
            started = time.perf_counter()
            # Read the result before updating shared counters.
            granted = await call()
            latencies.append((time.perf_counter() - started) * 1000)
            allowed += granted

    started = time.perf_counter()
    await asyncio.gather(*(run(c) for c in calls))
    return latencies, time.perf_counter() - started, allowed


def row(label: str, latencies: list[float], elapsed: float, allowed: int) -> str:
    return (
        f"| {label} | {len(latencies)} | {statistics.median(latencies):.2f} | "
        f"{percentile(latencies, 95):.2f} | {percentile(latencies, 99):.2f} | "
        f"{len(latencies) / elapsed:,.0f} | {allowed / len(latencies):.0%} |"
    )


async def main(args: argparse.Namespace) -> None:
    sizes = Sizes(args.users, args.groups, args.folders, args.documents)
    rng = random.Random(args.seed)
    settings = Settings(
        decision_log="off",
        # The random folder tree and nested groups run deeper than the default limit of 25.
        max_check_depth=60,
        cache_backend="memory",
        revision_quantization_ms=60_000,
        gc_enabled=False,
    )
    container = Container.build(settings)
    await container.start()
    store = await container.stores.create(f"bench {time.strftime('%H:%M:%S')}")
    try:
        await container.models.write(store.id, MODEL)
        tuples, owners = build_tuples(sizes, rng)
        load_started = time.perf_counter()
        batch = settings.max_tuples_per_write
        for i in range(0, len(tuples), batch):
            keys = [TupleKey.from_tuple(RelationTuple.parse(t)) for t in tuples[i : i + batch]]
            await container.tuples.write(store.id, WriteCommand(writes=keys))
        load_seconds = time.perf_counter() - load_started
        print(f"loaded {len(tuples):,} tuples in {load_seconds:.1f}s into {store.id}\n")

        # A third of the checks ask about a document's owner, so the mix contains both
        # short grants and full-depth denials that walk the folder hierarchy.
        documents = [rng.randrange(sizes.documents) for _ in range(args.checks)]
        queries = [(f"document:d{d}", rng.choice(["viewer", "editor"])) for d in documents]
        users = [
            f"user:u{owners[d] if rng.random() < 0.33 else rng.randrange(sizes.users)}"
            for d in documents
        ]

        def check_call(obj: str, relation: str, user: str) -> Callable[[], Awaitable[bool]]:
            async def call() -> bool:
                request = CheckRequest(tuple_key=TupleKey(object=obj, relation=relation, user=user))
                response = await container.queries.check(store.id, request, PRINCIPAL)
                return response.allowed

            return call

        calls = [check_call(o, r, u) for (o, r), u in zip(queries, users, strict=True)]
        print("| scenario | requests | p50 ms | p95 ms | p99 ms | req/s | allowed |")
        print("|---|---:|---:|---:|---:|---:|---:|")
        print(row("check, cold cache", *await timed(calls, args.concurrency)))
        print(row("check, warm cache", *await timed(calls, args.concurrency)))

        def list_call(user: str) -> Callable[[], Awaitable[bool]]:
            async def call() -> bool:
                request = ListObjectsRequest(object_type="document", relation="viewer", user=user)
                response = await container.queries.list_objects(store.id, request, PRINCIPAL)
                return bool(response.objects)

            return call

        sample = rng.sample(range(sizes.users), k=min(args.list_users, sizes.users))
        list_calls = [list_call(f"user:u{u}") for u in sample]
        print(row("list-objects", *await timed(list_calls, max(1, args.concurrency // 4))))
        stats = container.cache.stats
        print(
            f"\ncache hit rate {stats.hit_rate:.0%} ({stats.hits:,} hits, {stats.misses:,} misses)"
        )
    finally:
        # The synthetic tuples are only noise once the numbers are printed; dropping the
        # store cascades to its tuples, models and revisions.
        async with container.db.transaction() as session:
            await session.execute(delete(StoreRow).where(StoreRow.id == store.id))
        await container.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--users", type=int, default=2000)
    parser.add_argument("--groups", type=int, default=200)
    parser.add_argument("--folders", type=int, default=500)
    parser.add_argument("--documents", type=int, default=10_000)
    parser.add_argument("--checks", type=int, default=2000)
    parser.add_argument("--list-users", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--seed", type=int, default=42)
    asyncio.run(main(parser.parse_args()))
