"""Operational paths: pagination snapshots, key lifecycle, cache backends, the decision
flusher, store deletion, resolution limits and garbage collection."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select

from tests.integration.conftest import ClientFactory, tk
from tests.integration.test_api import SEED, check, write
from warden.db.database import Database
from warden.db.tables import TupleRow
from warden.decisions.repository import DecisionRepository
from warden.maintenance import GarbageCollector

EXCLUSION_CYCLE = """
model
  schema 1.1

type user

type doc
  relations
    define x: [user] but not y
    define y: x
"""


async def _new_store(client: httpx.AsyncClient, dsl: str) -> str:
    created = await client.post("/v1/stores", json={"name": "ops"})
    store_id: str = created.json()["id"]
    model = await client.post(f"/v1/stores/{store_id}/models", json={"dsl": dsl})
    assert model.status_code == 201, model.text
    return store_id


async def test_tuple_pages_stay_on_the_first_pages_snapshot(
    client: httpx.AsyncClient, store: dict[str, Any]
) -> None:
    sid = store["id"]
    viewers = [tk(f"document:d{n}", "viewer", "user:anne") for n in range(5)]
    first_write = await write(client, sid, writes=viewers)

    params: dict[str, str | int] = {"object_type": "document", "relation": "viewer", "limit": 2}
    page1 = (await client.get(f"/v1/stores/{sid}/tuples", params=params)).json()
    assert page1["revision"] == first_write["revision"]

    await write(client, sid, deletes=viewers[2:4], writes=[tk("document:d9", "viewer", "user:bo")])

    seen = [t["object"] for t in page1["items"]]
    cursor = page1["next_cursor"]
    while cursor:
        page = (
            await client.get(f"/v1/stores/{sid}/tuples", params={**params, "cursor": cursor})
        ).json()
        assert page["revision"] == first_write["revision"]
        seen.extend(t["object"] for t in page["items"])
        cursor = page["next_cursor"]
    assert seen == [f"document:d{n}" for n in range(5)], "later pages ignore later writes"

    fresh = (await client.get(f"/v1/stores/{sid}/tuples", params={**params, "limit": 10})).json()
    assert [t["object"] for t in fresh["items"]] == [
        "document:d0",
        "document:d1",
        "document:d4",
        "document:d9",
    ]

    bogus = await client.get(f"/v1/stores/{sid}/tuples", params={"cursor": "not-a-cursor"})
    assert bogus.json()["error"]["code"] == "invalid_cursor"


async def test_changes_feed_pages_newest_first(
    client: httpx.AsyncClient, store: dict[str, Any]
) -> None:
    sid = store["id"]
    await write(client, sid, writes=SEED[:2])
    await write(client, sid, writes=SEED[2:])
    await write(client, sid, deletes=SEED[:1])

    events: list[tuple[str, int]] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = (await client.get(f"/v1/stores/{sid}/changes", params=params)).json()
        events.extend((e["operation"], e["revision"]) for e in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert events == [("delete", 3), ("write", 2), ("write", 2), ("write", 1), ("write", 1)]


async def test_list_queries_report_truncation_and_stay_out_of_check_stats(
    client: httpx.AsyncClient, store: dict[str, Any]
) -> None:
    sid = store["id"]
    await write(client, sid, writes=[tk(f"document:d{n}", "owner", "user:anne") for n in range(6)])
    body = {"object_type": "document", "relation": "viewer", "user": "user:anne"}

    limited = (await client.post(f"/v1/stores/{sid}/list-objects", json=body | {"limit": 4})).json()
    assert limited["objects"] == [f"document:d{n}" for n in range(4)]
    assert limited["truncated"] is True
    complete = (await client.post(f"/v1/stores/{sid}/list-objects", json=body)).json()
    assert (len(complete["objects"]), complete["truncated"]) == (6, False)

    users = await client.post(
        f"/v1/stores/{sid}/list-users",
        json={
            "object": "document:d0",
            "relation": "viewer",
            "user_type": "user",
            "contextual_tuples": [tk("document:d0", "viewer", "user:zoe")],
        },
    )
    assert users.json()["users"] == ["user:anne", "user:zoe"]

    await check(client, sid, tk("document:d0", "viewer", "user:anne"))
    await check(client, sid, tk("document:d0", "viewer", "user:bo"))
    stats = (await client.get(f"/v1/stores/{sid}/decisions/stats")).json()
    assert (stats["total"], stats["allowed"], stats["denied"]) == (2, 1, 1)
    assert stats["list_queries"] == 3
    assert stats["allow_rate"] == 0.5


async def test_batch_check_reports_item_errors_with_codes(
    client: httpx.AsyncClient, store: dict[str, Any]
) -> None:
    sid = store["id"]
    await write(client, sid, writes=SEED)
    response = await client.post(
        f"/v1/stores/{sid}/batch-check",
        json={
            "checks": [
                {"tuple_key": tk("document:roadmap", relation, "user:anne"), "correlation_id": cid}
                for cid, relation in (("ok", "viewer"), ("bad", "nope"))
            ],
            "contextual_tuples": [tk("group:eng", "member", "user:zoe")],
        },
    )
    results = {r["correlation_id"]: r for r in response.json()["results"]}
    assert results["ok"]["allowed"] is True
    assert results["ok"]["decision_id"].startswith("dec_")
    assert results["bad"]["error_code"] == "invalid_tuple"


async def test_contextual_results_never_enter_the_shared_cache(
    client: httpx.AsyncClient, store: dict[str, Any]
) -> None:
    sid = store["id"]
    await write(client, sid, writes=SEED)
    key = tk("document:roadmap", "editor", "user:zoe")
    context = [tk("group:eng", "member", "user:zoe")]
    first = await check(client, sid, key, contextual_tuples=context)
    second = await check(client, sid, key, contextual_tuples=context)
    assert first["allowed"]
    assert second["allowed"]
    assert second["stats"]["cache_hits"] == 0
    assert not second["cached"]


async def test_resolution_limits_surface_as_errors(client_factory: ClientFactory) -> None:
    shallow = await client_factory(max_check_depth=3)
    sid = await _new_store(
        shallow,
        "type user\ntype folder\n  relations\n    define parent: [folder]\n"
        "    define viewer: [user] or viewer from parent\n",
    )
    chain = [tk(f"folder:f{n}", "parent", f"folder:f{n + 1}") for n in range(6)]
    await write(shallow, sid, writes=chain)
    deep = await shallow.post(
        f"/v1/stores/{sid}/check", json={"tuple_key": tk("folder:f0", "viewer", "user:anne")}
    )
    assert deep.status_code == 422
    assert deep.json()["error"]["code"] == "resolution_too_complex"

    sid = await _new_store(shallow, EXCLUSION_CYCLE)
    await write(shallow, sid, writes=[tk("doc:1", "x", "user:anne")])
    paradox = await shallow.post(
        f"/v1/stores/{sid}/check", json={"tuple_key": tk("doc:1", "x", "user:anne")}
    )
    assert paradox.status_code == 422
    assert "did not converge" in paradox.json()["error"]["message"]


async def test_revocation_lag_is_bounded_by_the_principal_cache(
    client: httpx.AsyncClient, client_factory: ClientFactory, store: dict[str, Any]
) -> None:
    sid = store["id"]
    created = (
        await client.post("/v1/api-keys", json={"name": "r", "scopes": ["check"], "store_id": sid})
    ).json()
    probe = {"tuple_key": SEED[0]}
    caching_replica = await client_factory(api_key=created["key"])
    strict_replica = await client_factory(api_key=created["key"], principal_cache_ttl_seconds=0)
    for replica in (caching_replica, strict_replica):
        assert (await replica.post(f"/v1/stores/{sid}/check", json=probe)).status_code == 200

    revoker = await client_factory()
    assert (await revoker.delete(f"/v1/api-keys/{created['id']}")).status_code == 204
    assert (await strict_replica.post(f"/v1/stores/{sid}/check", json=probe)).status_code == 401
    lagging = await caching_replica.post(f"/v1/stores/{sid}/check", json=probe)
    assert lagging.status_code == 200, "other replicas honour revocation after the cache TTL"


async def test_key_management_needs_its_own_scope(
    client: httpx.AsyncClient, client_factory: ClientFactory, store: dict[str, Any]
) -> None:
    console_scopes = ["stores:admin", "models:read", "tuples:write", "check", "decisions:read"]
    console = (
        await client.post("/v1/api-keys", json={"name": "console", "scopes": console_scopes})
    ).json()
    as_console = await client_factory(api_key=console["key"])
    assert (await as_console.get("/v1/api-keys")).status_code == 403
    assert (await as_console.post("/v1/stores", json={"name": "ok"})).status_code == 201

    escalation = await client.post(
        "/v1/api-keys",
        json={"name": "bad", "scopes": ["keys:admin"], "store_id": store["id"]},
    )
    assert escalation.status_code == 403


async def test_redis_cache_shares_results_and_degrades_to_a_miss(
    client_factory: ClientFactory,
) -> None:
    redis_url = os.environ.get("WARDEN_TEST_REDIS_URL", "redis://127.0.0.1:6406/15")
    probe = Redis.from_url(redis_url, socket_timeout=0.25)
    try:
        await probe.ping()
    except (RedisError, OSError):
        pytest.skip(f"Redis is not reachable at {redis_url}")
    finally:
        await probe.aclose()

    replica_a = await client_factory(cache_backend="redis", redis_url=redis_url)
    replica_b = await client_factory(cache_backend="redis", redis_url=redis_url)
    sid = await _new_store(
        replica_a, "type user\ntype doc\n  relations\n    define viewer: [user]\n"
    )
    await write(replica_a, sid, writes=[tk("doc:1", "viewer", "user:anne")])
    key = tk("doc:1", "viewer", "user:anne")
    consistency = {"mode": "fully_consistent"}
    assert not (await check(replica_a, sid, key, consistency=consistency))["cached"]
    assert (await check(replica_b, sid, key, consistency=consistency))["cached"]

    broken = await client_factory(cache_backend="redis", redis_url="redis://127.0.0.1:1/0")
    degraded = await check(broken, sid, key, consistency=consistency)
    assert degraded["allowed"]
    assert not degraded["cached"]


async def test_async_decision_log_flushes_in_the_background(
    client_factory: ClientFactory,
) -> None:
    client = await client_factory(decision_log="async", decision_flush_interval_ms=20)
    sid = await _new_store(client, "type user\ntype doc\n  relations\n    define viewer: [user]\n")
    decision = await check(client, sid, tk("doc:1", "viewer", "user:anne"))
    for _ in range(100):
        found = await client.get(f"/v1/stores/{sid}/decisions/{decision['decision_id']}")
        if found.status_code == 200:
            break
        await asyncio.sleep(0.02)
    assert found.status_code == 200
    assert found.json()["allowed"] is False


async def test_deleted_stores_disappear_everywhere(
    client: httpx.AsyncClient, store: dict[str, Any]
) -> None:
    sid = store["id"]
    await write(client, sid, writes=SEED)
    assert (await client.delete(f"/v1/stores/{sid}")).status_code == 204

    assert (await client.get(f"/v1/stores/{sid}")).status_code == 404
    assert (await client.get(f"/v1/stores/{sid}/models/latest")).status_code == 404
    assert (await client.get(f"/v1/stores/{sid}/models/{store['model_id']}")).status_code == 404
    gone = await client.post(f"/v1/stores/{sid}/check", json={"tuple_key": SEED[0]})
    assert gone.status_code == 404
    assert (
        await client.post(f"/v1/stores/{sid}/tuples/write", json={"writes": SEED})
    ).status_code == 404
    listed = (await client.get("/v1/stores", params={"limit": 200})).json()
    assert sid not in {s["id"] for s in listed["items"]}
    assert (await client.delete(f"/v1/stores/{sid}")).status_code == 404


async def test_request_ids_are_echoed_only_when_well_formed(client: httpx.AsyncClient) -> None:
    good = await client.get("/healthz", headers={"X-Request-ID": "req-123.abc_DEF"})
    assert good.headers["x-request-id"] == "req-123.abc_DEF"
    bad = await client.get("/healthz", headers={"X-Request-ID": "x" * 65})
    assert bad.headers["x-request-id"] != "x" * 65
    assert len(bad.headers["x-request-id"]) == 32


async def test_garbage_collection_drops_history_behind_the_horizon(
    client: httpx.AsyncClient, database: str
) -> None:
    sid = await _new_store(client, "type user\ntype doc\n  relations\n    define viewer: [user]\n")
    granted = await write(client, sid, writes=[tk("doc:1", "viewer", "user:anne")])
    revoked = await write(client, sid, deletes=[tk("doc:1", "viewer", "user:anne")])
    key = tk("doc:1", "viewer", "user:anne")
    past = {"mode": "at_exact_snapshot", "token": granted["consistency_token"]}
    assert (await check(client, sid, key, consistency=past))["allowed"]

    db = Database(database, pool_size=2, max_overflow=0)
    try:
        gc = GarbageCollector(
            db,
            DecisionRepository(db),
            history_retention=timedelta(hours=1),
            decision_retention=timedelta(days=365),
            interval_seconds=3600,
        )
        report = await gc.run_once(now=datetime.now(UTC) + timedelta(hours=2))
        assert report.stores_advanced >= 1
        assert report.tuples_removed >= 1
        async with db.session() as session:
            rows = await session.scalar(
                select(func.count()).select_from(TupleRow).where(TupleRow.store_id == sid)
            )
        assert rows == 0
    finally:
        await db.dispose()

    expired = await client.post(
        f"/v1/stores/{sid}/check", json={"tuple_key": key, "consistency": past}
    )
    assert expired.status_code == 400
    assert expired.json()["error"]["code"] == "snapshot_too_old"
    current = {"mode": "at_exact_snapshot", "token": revoked["consistency_token"]}
    assert not (await check(client, sid, key, consistency=current))["allowed"]
    fresh = {"mode": "at_least_as_fresh", "token": granted["consistency_token"]}
    assert not (await check(client, sid, key, consistency=fresh))["allowed"]
