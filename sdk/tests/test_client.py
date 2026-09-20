from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import Depends, FastAPI

from warden_sdk import (
    CheckResult,
    Consistency,
    TupleKey,
    WardenBatchCheckError,
    WardenClient,
    WardenConflictError,
    WardenUnavailableError,
)
from warden_sdk.fastapi import WardenGuard

TOKEN = "zk1.abc"


def _check_payload(allowed: bool) -> dict[str, Any]:
    return {
        "allowed": allowed,
        "decision_id": "dec_1",
        "cached": False,
        "model_id": "md_1",
        "revision": 7,
        "consistency_token": TOKEN,
        "duration_ms": 1.5,
        "trace": {"kind": "check", "label": "document:1#viewer", "result": "allowed"},
        "stats": {"dispatches": 1, "memo_hits": 0, "cache_hits": 0, "queries": 1},
    }


class Recorder:
    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)

    def body(self, index: int) -> dict[str, Any]:
        payload: dict[str, Any] = json.loads(self.requests[index].content)
        return payload


def _client(recorder: Recorder, **kwargs: Any) -> WardenClient:
    return WardenClient(
        "http://warden",
        "wdn_key",
        store_id="st_1",
        transport=httpx.MockTransport(recorder),
        **kwargs,
    )


def _router(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/tuples/write"):
        return httpx.Response(
            200,
            json={
                "revision": 7,
                "consistency_token": TOKEN,
                "model_id": "md_1",
                "written": 1,
                "deleted": 0,
            },
        )
    return httpx.Response(200, json=_check_payload(True))


def test_tuple_key_notation() -> None:
    key = TupleKey.parse("document:1#viewer@group:eng#member")
    assert (key.object, key.relation, key.user) == ("document:1", "viewer", "group:eng#member")
    with pytest.raises(ValueError, match="notation"):
        TupleKey.parse("document:1@user:anne")
    email = TupleKey.parse("mailbox:anne@lumen.dev#owner@user:anne@lumen.dev")
    assert (email.object, email.relation, email.user) == (
        "mailbox:anne@lumen.dev",
        "owner",
        "user:anne@lumen.dev",
    )
    assert TupleKey.parse(str(email)) == email


async def test_reads_after_writes_carry_the_write_token() -> None:
    recorder = Recorder(_router)
    async with _client(recorder) as client:
        await client.check("document:1", "viewer", "user:anne")
        await client.write(["document:1#viewer@user:anne"])
        result = await client.check("document:1", "viewer", "user:anne")
    assert result.allowed
    assert recorder.body(0)["consistency"] is None
    assert recorder.requests[0].headers["authorization"] == "Bearer wdn_key"
    assert recorder.body(1)["writes"] == [
        {"object": "document:1", "relation": "viewer", "user": "user:anne"}
    ]
    assert recorder.body(2)["consistency"] == {"mode": "at_least_as_fresh", "token": TOKEN}


async def test_read_your_writes_can_be_disabled_and_overridden() -> None:
    recorder = Recorder(_router)
    async with _client(recorder, read_your_writes=False) as client:
        await client.write(["document:1#viewer@user:anne"])
        await client.check("document:1", "viewer", "user:anne")
        await client.check("document:1", "viewer", "user:anne", consistency=Consistency.full())
    assert recorder.body(1)["consistency"] is None
    assert recorder.body(2)["consistency"] == {"mode": "fully_consistent"}


async def test_errors_are_typed() -> None:
    def conflict(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={
                "error": {"code": "conflict", "message": "1 tuple(s) already exist", "details": []}
            },
        )

    async with _client(Recorder(conflict)) as client:
        with pytest.raises(WardenConflictError) as exc_info:
            await client.write(["document:1#viewer@user:anne"])
    assert exc_info.value.code == "conflict"


async def test_unavailable_responses_are_retried() -> None:
    attempts = iter([503, 503, 200])

    def flaky(_: httpx.Request) -> httpx.Response:
        status = next(attempts)
        if status == 200:
            return httpx.Response(200, json=_check_payload(False))
        return httpx.Response(status, json={"error": {"code": "unavailable", "message": "busy"}})

    recorder = Recorder(flaky)
    async with _client(recorder, retries=2) as client:
        result = await client.check("document:1", "viewer", "user:anne")
    assert not result.allowed
    assert len(recorder.requests) == 3

    async with _client(Recorder(lambda _: httpx.Response(503, text="down")), retries=1) as client:
        with pytest.raises(WardenUnavailableError):
            await client.check("document:1", "viewer", "user:anne")


def _write_payload() -> dict[str, Any]:
    return {
        "revision": 7,
        "consistency_token": TOKEN,
        "model_id": "md_1",
        "written": 1,
        "deleted": 0,
    }


async def test_strict_writes_are_not_retried_once_sent() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no response", request=request)

    recorder = Recorder(timeout)
    async with _client(recorder, retries=3) as client:
        with pytest.raises(WardenUnavailableError):
            await client.write(["document:1#viewer@user:anne"])
    assert len(recorder.requests) == 1, "a committed write must not be replayed"

    busy = {"error": {"code": "unavailable", "message": "busy"}}
    recorder = Recorder(lambda _: httpx.Response(503, json=busy))
    async with _client(recorder, retries=3) as client:
        with pytest.raises(WardenUnavailableError):
            await client.write(["document:1#viewer@user:anne"])
    assert len(recorder.requests) == 1


async def test_writes_retry_when_unsent_or_repeatable() -> None:
    attempts = iter(["connect", "ok"])

    def refuse_once(request: httpx.Request) -> httpx.Response:
        if next(attempts) == "connect":
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json=_write_payload())

    recorder = Recorder(refuse_once)
    async with _client(recorder, retries=2) as client:
        await client.write(["document:1#viewer@user:anne"])
    assert len(recorder.requests) == 2

    outcomes = iter([503, 200])

    def flaky(_: httpx.Request) -> httpx.Response:
        if next(outcomes) == 503:
            return httpx.Response(503, json={"error": {"code": "unavailable", "message": "busy"}})
        return httpx.Response(200, json=_write_payload())

    recorder = Recorder(flaky)
    async with _client(recorder, retries=2) as client:
        await client.write(
            ["document:1#viewer@user:anne"], on_duplicate="ignore", on_missing="ignore"
        )
    assert len(recorder.requests) == 2


async def test_for_store_shares_the_pool_and_tokens() -> None:
    recorder = Recorder(_router)
    async with _client(recorder) as client:
        other = client.for_store("st_2")
        await other.write(["document:1#viewer@user:anne"])
        await client.for_store("st_2").check("document:1", "viewer", "user:anne")
        await other.aclose()
        await client.check("document:1", "viewer", "user:anne")
    assert recorder.requests[0].url.path == "/v1/stores/st_2/tuples/write"
    assert recorder.requests[0].headers["authorization"] == "Bearer wdn_key"
    assert recorder.body(1)["consistency"] == {"mode": "at_least_as_fresh", "token": TOKEN}
    assert recorder.body(2)["consistency"] is None, "tokens are tracked per store"


async def test_batch_check_errors_are_not_denials() -> None:
    def batch(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model_id": "md_1",
                "revision": 1,
                "consistency_token": TOKEN,
                "duration_ms": 1.0,
                "results": [
                    {
                        "correlation_id": "bad",
                        "tuple_key": {"object": "d:1", "relation": "nope", "user": "user:a"},
                        "allowed": False,
                        "error": "relation 'd#nope' is not defined in the model",
                        "error_code": "invalid_tuple",
                    },
                ],
            },
        )

    async with _client(Recorder(batch)) as client:
        with pytest.raises(WardenBatchCheckError) as exc_info:
            await client.batch_check({"bad": "d:1#nope@user:a"})
        items = await client.batch_check_items({"bad": "d:1#nope@user:a"})
    assert list(exc_info.value.failed) == ["bad"]
    assert items["bad"].error_code == "invalid_tuple"


async def test_batch_check_maps_correlation_ids() -> None:
    def batch(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model_id": "md_1",
                "revision": 1,
                "consistency_token": TOKEN,
                "duration_ms": 1.0,
                "results": [
                    {
                        "correlation_id": "edit",
                        "tuple_key": {"object": "d:1", "relation": "editor", "user": "user:a"},
                        "allowed": False,
                    },
                    {
                        "correlation_id": "view",
                        "tuple_key": {"object": "d:1", "relation": "viewer", "user": "user:a"},
                        "allowed": True,
                    },
                ],
            },
        )

    async with _client(Recorder(batch)) as client:
        result = await client.batch_check(
            {"edit": "d:1#editor@user:a", "view": "d:1#viewer@user:a"}
        )
    assert result == {"edit": False, "view": True}


async def test_fastapi_guard_allows_and_denies() -> None:
    def decide(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json=_check_payload(body["tuple_key"]["user"] == "user:anne"))

    warden = _client(Recorder(decide))

    def current_subject(user: str = "anne") -> str:
        return f"user:{user}"

    guard = WardenGuard(client=lambda: warden, subject=current_subject)
    can_view = guard.require("viewer", "document", "document_id")
    app = FastAPI()

    @app.get("/documents/{document_id}")
    async def read_document(
        document_id: str, decision: CheckResult = Depends(can_view)
    ) -> dict[str, str]:
        return {"id": document_id, "decision": decision.decision_id}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://app") as http:
        ok = await http.get("/documents/roadmap", params={"user": "anne"})
        denied = await http.get("/documents/roadmap", params={"user": "zoe"})
    await warden.aclose()

    assert ok.json() == {"id": "roadmap", "decision": "dec_1"}
    assert denied.status_code == 403
    assert denied.json()["detail"]["decision_id"] == "dec_1"
