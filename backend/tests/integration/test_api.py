from __future__ import annotations

from typing import Any

import httpx

from tests.helpers import WORKSPACE_MODEL
from tests.integration.conftest import ClientFactory, tk

SEED = [
    tk("group:eng", "member", "user:anne"),
    tk("folder:root", "editor", "group:eng#member"),
    tk("document:roadmap", "parent", "folder:root"),
    tk("document:roadmap", "owner", "user:carl"),
]


async def write(
    client: httpx.AsyncClient, store_id: str, *, expect: int = 200, **body: Any
) -> dict[str, Any]:
    response = await client.post(f"/v1/stores/{store_id}/tuples/write", json=body)
    assert response.status_code == expect, response.text
    result: dict[str, Any] = response.json()
    return result


async def check(
    client: httpx.AsyncClient, store_id: str, key: dict[str, str], **extra: Any
) -> dict[str, Any]:
    response = await client.post(f"/v1/stores/{store_id}/check", json={"tuple_key": key, **extra})
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


async def test_health(client: httpx.AsyncClient) -> None:
    assert (await client.get("/healthz")).json()["status"] == "ok"
    assert (await client.get("/readyz")).json()["database"] == "ok"


async def test_model_validation_reports_positions(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/dsl/validate", json={"dsl": "type user\ntype doc\n  relations\n    define v: [usr]\n"}
    )
    body = response.json()
    assert body["valid"] is False
    assert body["issues"][0] | {"message": ""} == {
        "code": "unknown_type",
        "message": "",
        "line": 4,
        "column": 16,
        "end_line": 4,
        "end_column": 19,
        "severity": "error",
    }
    ok = (await client.post("/v1/dsl/validate", json={"dsl": WORKSPACE_MODEL})).json()
    assert ok["valid"]
    assert ok["formatted"].startswith("model\n  schema 1.1")


async def test_models_are_versioned(client: httpx.AsyncClient, store: dict[str, Any]) -> None:
    sid = store["id"]
    bad = await client.post(f"/v1/stores/{sid}/models", json={"dsl": "type doc relations define"})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "invalid_model"
    assert bad.json()["error"]["details"][0]["line"] == 1

    second = await client.post(f"/v1/stores/{sid}/models", json={"dsl": WORKSPACE_MODEL})
    assert second.json()["version"] == 2
    latest = (await client.get(f"/v1/stores/{sid}/models/latest")).json()
    assert latest["id"] == second.json()["id"]
    page = (await client.get(f"/v1/stores/{sid}/models", params={"limit": 1})).json()
    assert [m["version"] for m in page["items"]] == [2]
    rest = await client.get(f"/v1/stores/{sid}/models", params={"cursor": page["next_cursor"]})
    assert [m["version"] for m in rest.json()["items"]] == [1]


async def test_writes_bump_revision_and_enforce_preconditions(
    client: httpx.AsyncClient, store: dict[str, Any]
) -> None:
    sid = store["id"]
    first = await write(client, sid, writes=SEED)
    assert (first["revision"], first["written"]) == (1, 4)

    duplicate = await write(client, sid, expect=409, writes=SEED[:1])
    assert duplicate["error"]["code"] == "conflict"
    ignored = await write(client, sid, writes=SEED[:1], on_duplicate="ignore")
    assert (ignored["revision"], ignored["written"]) == (1, 0), "no-op batches keep the revision"
    assert ignored["consistency_token"] == first["consistency_token"]

    failed = await write(
        client,
        sid,
        expect=409,
        writes=[tk("document:roadmap", "owner", "user:dana")],
        preconditions=[{"tuple_key": SEED[3], "must_exist": False}],
    )
    assert failed["error"]["code"] == "precondition_failed"

    swapped = await write(
        client,
        sid,
        writes=[tk("document:roadmap", "owner", "user:dana")],
        deletes=[SEED[3]],
        preconditions=[{"tuple_key": SEED[3], "must_exist": True}],
    )
    assert (swapped["written"], swapped["deleted"]) == (1, 1)
    assert swapped["revision"] == 2, "rejected batches roll back their revision"

    missing = await write(client, sid, expect=409, deletes=[SEED[3]])
    assert "do not exist" in missing["error"]["message"]

    invalid = await write(client, sid, expect=422, writes=[tk("document:x", "parent", "user:anne")])
    assert invalid["error"]["details"][0]["reason"].endswith("which accepts [folder]")

    owners = (
        await client.get(
            f"/v1/stores/{sid}/tuples",
            params={"object_type": "document", "relation": "owner"},
        )
    ).json()
    assert [t["user"] for t in owners["items"]] == ["user:dana"]

    changes = (await client.get(f"/v1/stores/{sid}/changes", params={"limit": 2})).json()
    assert [(c["operation"], c["revision"]) for c in changes["items"]] == [
        ("write", 2),
        ("delete", 2),
    ]
    assert changes["next_cursor"]


async def test_snapshot_reads_see_history(client: httpx.AsyncClient, store: dict[str, Any]) -> None:
    sid = store["id"]
    granted = await write(client, sid, writes=SEED)
    revoked = await write(client, sid, deletes=[SEED[0]])
    key = tk("document:roadmap", "editor", "user:anne")

    past = await check(
        client,
        sid,
        key,
        consistency={"mode": "at_exact_snapshot", "token": granted["consistency_token"]},
    )
    assert past["allowed"]
    assert past["revision"] == granted["revision"]

    now = await check(client, sid, key, consistency={"mode": "fully_consistent"})
    assert not now["allowed"]
    assert now["revision"] == revoked["revision"]


async def test_tokens_close_the_new_enemy_window(
    client_factory: ClientFactory, store: dict[str, Any]
) -> None:
    """Two API replicas share one database. The reader caches revisions for a minute,
    so without a token it keeps answering from its stale snapshot."""
    writer = await client_factory()
    reader = await client_factory(revision_quantization_ms=60_000)
    sid = store["id"]
    key = tk("document:roadmap", "viewer", "user:anne")

    await write(writer, sid, writes=SEED)
    assert (await check(reader, sid, key, consistency={"mode": "fully_consistent"}))["allowed"]

    removal = await write(writer, sid, deletes=[SEED[0]])
    stale = await check(reader, sid, key)
    assert stale["allowed"], "minimize_latency is allowed to serve the cached revision"

    fresh = await check(
        reader,
        sid,
        key,
        consistency={"mode": "at_least_as_fresh", "token": removal["consistency_token"]},
    )
    assert not fresh["allowed"]
    assert fresh["revision"] >= removal["revision"]

    other = await client_factory()
    foreign = await other.post("/v1/stores", json={"name": "other"})
    await other.post(f"/v1/stores/{foreign.json()['id']}/models", json={"dsl": WORKSPACE_MODEL})
    bad = await reader.post(
        f"/v1/stores/{foreign.json()['id']}/check",
        json={
            "tuple_key": key,
            "consistency": {"mode": "at_least_as_fresh", "token": removal["consistency_token"]},
        },
    )
    assert bad.json()["error"]["code"] == "invalid_consistency_token"


async def test_check_trace_expand_and_lists(
    client: httpx.AsyncClient, store: dict[str, Any]
) -> None:
    sid = store["id"]
    await write(client, sid, writes=SEED)

    result = await check(client, sid, tk("document:roadmap", "editor", "user:anne"), explain=True)
    assert result["allowed"]
    assert result["stats"]["queries"] > 0
    assert result["trace"]["label"] == "document:roadmap#editor"
    assert result["trace"]["children"][0]["kind"] == "union"

    repeat = await check(client, sid, tk("document:roadmap", "editor", "user:anne"))
    assert repeat["cached"]
    assert repeat["stats"]["queries"] == 0

    expanded = await client.post(
        f"/v1/stores/{sid}/expand", json={"object": "document:roadmap", "relation": "editor"}
    )
    assert expanded.json()["tree"]["kind"] == "userset"

    objects = await client.post(
        f"/v1/stores/{sid}/list-objects",
        json={"object_type": "document", "relation": "viewer", "user": "user:anne"},
    )
    assert objects.json()["objects"] == ["document:roadmap"]

    users = await client.post(
        f"/v1/stores/{sid}/list-users",
        json={"object": "document:roadmap", "relation": "viewer", "user_type": "user"},
    )
    assert users.json()["users"] == ["user:anne", "user:carl"]

    batch = await client.post(
        f"/v1/stores/{sid}/batch-check",
        json={
            "checks": [
                {
                    "tuple_key": tk("document:roadmap", "can_share", "user:carl"),
                    "correlation_id": "a",
                },
                {"tuple_key": tk("document:roadmap", "owner", "user:anne"), "correlation_id": "b"},
                {"tuple_key": tk("document:roadmap", "nope", "user:anne"), "correlation_id": "c"},
            ]
        },
    )
    results = {r["correlation_id"]: r for r in batch.json()["results"]}
    assert results["a"]["allowed"] is True
    assert results["b"]["allowed"] is False
    assert "not defined" in results["c"]["error"]


async def test_contextual_tuples_do_not_persist(
    client: httpx.AsyncClient, store: dict[str, Any]
) -> None:
    sid = store["id"]
    await write(client, sid, writes=SEED)
    key = tk("document:roadmap", "editor", "user:zoe")
    with_context = await check(
        client, sid, key, contextual_tuples=[tk("group:eng", "member", "user:zoe")]
    )
    assert with_context["allowed"]
    assert not (await check(client, sid, key))["allowed"]

    invalid = await client.post(
        f"/v1/stores/{sid}/check",
        json={"tuple_key": key, "contextual_tuples": [tk("group:eng", "owner", "user:zoe")]},
    )
    assert invalid.status_code == 422


async def test_unknown_relations_are_rejected(
    client: httpx.AsyncClient, store: dict[str, Any]
) -> None:
    response = await client.post(
        f"/v1/stores/{store['id']}/check",
        json={"tuple_key": tk("document:x", "approver", "user:anne")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_tuple"


async def test_checks_can_pin_an_older_model(
    client: httpx.AsyncClient, store: dict[str, Any]
) -> None:
    sid = store["id"]
    await write(client, sid, writes=SEED)
    narrowed = WORKSPACE_MODEL.replace(" or editor from parent", "")
    await client.post(f"/v1/stores/{sid}/models", json={"dsl": narrowed})
    key = tk("document:roadmap", "editor", "user:anne")

    assert not (await check(client, sid, key))["allowed"]
    pinned = await check(client, sid, key, model_id=store["model_id"])
    assert pinned["allowed"]
    assert pinned["model_id"] == store["model_id"]


async def test_decisions_are_logged_with_traces(
    client: httpx.AsyncClient, store: dict[str, Any]
) -> None:
    sid = store["id"]
    await write(client, sid, writes=SEED)
    decision = await check(client, sid, tk("document:roadmap", "viewer", "user:anne"))
    await check(client, sid, tk("document:roadmap", "viewer", "user:zoe"))

    page = (await client.get(f"/v1/stores/{sid}/decisions")).json()
    assert len(page["items"]) == 2
    denied = (await client.get(f"/v1/stores/{sid}/decisions", params={"allowed": False})).json()
    assert [d["subject"] for d in denied["items"]] == ["user:zoe"]

    detail = (await client.get(f"/v1/stores/{sid}/decisions/{decision['decision_id']}")).json()
    assert detail["trace"]["label"] == "document:roadmap#viewer"

    stats = (await client.get(f"/v1/stores/{sid}/decisions/stats")).json()
    assert (stats["total"], stats["allowed"], stats["denied"]) == (2, 1, 1)
    overview = (await client.get(f"/v1/stores/{sid}/overview")).json()
    assert overview["tuple_count"] == 4
    assert overview["model_count"] == 1


async def test_api_keys_enforce_scope_and_store(
    client: httpx.AsyncClient, client_factory: ClientFactory, store: dict[str, Any]
) -> None:
    sid = store["id"]
    anonymous = await client_factory(api_key=None)
    assert (await anonymous.get(f"/v1/stores/{sid}")).status_code == 401

    created = await client.post(
        "/v1/api-keys", json={"name": "checker", "scopes": ["check"], "store_id": sid}
    )
    assert created.status_code == 201
    key = created.json()
    scoped = await client_factory(api_key=key["key"])

    assert (
        await scoped.post(f"/v1/stores/{sid}/check", json={"tuple_key": SEED[0]})
    ).status_code == 200
    forbidden = await scoped.post(f"/v1/stores/{sid}/tuples/write", json={"writes": SEED})
    assert forbidden.status_code == 403
    other = (await client.post("/v1/stores", json={"name": "elsewhere"})).json()
    assert (
        await scoped.post(f"/v1/stores/{other['id']}/check", json={"tuple_key": SEED[0]})
    ).status_code == 403

    escalation = await client.post(
        "/v1/api-keys", json={"name": "bad", "scopes": ["stores:admin"], "store_id": sid}
    )
    assert escalation.status_code == 403

    assert (await client.delete(f"/v1/api-keys/{key['id']}")).status_code == 204
    revoked = await client_factory(api_key=key["key"])
    assert (
        await revoked.post(f"/v1/stores/{sid}/check", json={"tuple_key": SEED[0]})
    ).status_code == 401

    garbage = await client_factory(api_key="not-a-key")
    assert (await garbage.get("/v1/stores")).json()["error"]["code"] == "unauthenticated"


async def test_validation_errors_use_the_error_envelope(
    client: httpx.AsyncClient, store: dict[str, Any]
) -> None:
    response = await client.post(
        f"/v1/stores/{store['id']}/check",
        json={"tuple_key": {"object": "document", "relation": "viewer", "user": "user:anne"}},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert error["details"][0]["location"].startswith("body.tuple_key")
    missing = await client.get("/v1/stores/st_missing")
    assert missing.status_code == 404
