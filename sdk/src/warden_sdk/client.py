from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping, Sequence
from types import TracebackType
from typing import Any, Literal, Self

import httpx
from pydantic import BaseModel

from warden_sdk.errors import (
    WardenBatchCheckError,
    WardenError,
    WardenUnavailableError,
    error_for,
)
from warden_sdk.models import (
    AuthorizationModel,
    BatchCheckItem,
    BatchCheckResult,
    CheckResult,
    Consistency,
    ErrorPayload,
    ExpandResult,
    ListObjectsResult,
    ListUsersResult,
    Store,
    TupleKey,
    TupleLike,
    TuplePage,
    WriteResult,
    as_key,
)

_RETRYABLE = {502, 503, 504}
# Failures that happen before the request leaves the client, so retrying cannot repeat it.
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


class WardenClient:
    """Async client for one Warden store.

    With `read_your_writes` enabled (the default) the client remembers the consistency
    token of its latest write and sends it as at_least_as_fresh on later reads, so a
    permission change made through this client is never followed by a stale check.

    Reads (GETs, check, expand and the list calls) are retried on connection errors and
    502/503/504. A write is retried only when repeating it is harmless: when it never
    left the client, or when it uses on_duplicate="ignore" and on_missing="ignore"
    without preconditions.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        store_id: str | None = None,
        timeout: float = 5.0,
        retries: int = 2,
        read_your_writes: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._configure(
            http
            or httpx.AsyncClient(
                base_url=base_url.rstrip("/"),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "User-Agent": "warden-sdk-python/0.1",
                },
                timeout=timeout,
                transport=transport,
            ),
            owns_http=http is None,
            store_id=store_id,
            retries=retries,
            read_your_writes=read_your_writes,
            tokens={},
        )

    def _configure(
        self,
        http: httpx.AsyncClient,
        *,
        owns_http: bool,
        store_id: str | None,
        retries: int,
        read_your_writes: bool,
        tokens: dict[str, tuple[int, str]],
    ) -> None:
        self._http = http
        self._owns_http = owns_http
        self._store_id = store_id
        self._retries = retries
        self._read_your_writes = read_your_writes
        self._tokens = tokens

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    def for_store(self, store_id: str) -> Self:
        """A client bound to another store that shares this client's connection pool and
        write tokens. Closing it leaves the shared pool open."""
        clone = type(self).__new__(type(self))
        clone._configure(
            self._http,
            owns_http=False,
            store_id=store_id,
            retries=self._retries,
            read_your_writes=self._read_your_writes,
            tokens=self._tokens,
        )
        return clone

    @property
    def store_id(self) -> str:
        if self._store_id is None:
            raise ValueError("this client is not bound to a store; use for_store()")
        return self._store_id

    def last_token(self) -> str | None:
        entry = self._tokens.get(self.store_id)
        return entry[1] if entry else None

    def _remember(self, revision: int, token: str) -> None:
        current = self._tokens.get(self.store_id)
        if current is None or revision > current[0]:
            self._tokens[self.store_id] = (revision, token)

    def _consistency(self, explicit: Consistency | None) -> dict[str, Any] | None:
        if explicit is not None:
            return explicit.model_dump(mode="json", exclude_none=True)
        token = self.last_token() if self._read_your_writes else None
        if token is None:
            return None
        return Consistency.at_least_as_fresh(token).model_dump(mode="json")

    async def _request[T: BaseModel](
        self,
        method: Literal["GET", "POST", "DELETE"],
        path: str,
        model: type[T],
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        idempotent: bool | None = None,
    ) -> T:
        response = await self._send(
            method,
            path,
            json=json,
            params=params,
            idempotent=method == "GET" if idempotent is None else idempotent,
        )
        return model.model_validate(response.json())

    async def _send(
        self,
        method: Literal["GET", "POST", "DELETE"],
        path: str,
        *,
        json: Mapping[str, Any] | None,
        params: Mapping[str, Any] | None,
        idempotent: bool,
    ) -> httpx.Response:
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        attempt = 0
        while True:
            try:
                response = await self._http.request(method, path, json=json, params=clean_params)
            except httpx.TransportError as exc:
                retryable = idempotent or isinstance(exc, _NOT_SENT)
                if not retryable or attempt >= self._retries:
                    raise WardenUnavailableError(0, "unavailable", str(exc)) from exc
            else:
                if response.status_code < 400:
                    return response
                retryable = idempotent and response.status_code in _RETRYABLE
                if not retryable or attempt >= self._retries:
                    raise _error(response)
            attempt += 1
            await asyncio.sleep(0.05 * 2**attempt)

    async def create_store(self, name: str) -> Store:
        return await self._request("POST", "/v1/stores", Store, json={"name": name})

    async def get_store(self) -> Store:
        return await self._request("GET", f"/v1/stores/{self.store_id}", Store)

    async def write_model(self, dsl: str) -> AuthorizationModel:
        return await self._request(
            "POST", f"/v1/stores/{self.store_id}/models", AuthorizationModel, json={"dsl": dsl}
        )

    async def latest_model(self) -> AuthorizationModel:
        return await self._request(
            "GET", f"/v1/stores/{self.store_id}/models/latest", AuthorizationModel
        )

    async def write(
        self,
        writes: Iterable[TupleLike] = (),
        deletes: Iterable[TupleLike] = (),
        *,
        must_exist: Iterable[TupleLike] = (),
        must_not_exist: Iterable[TupleLike] = (),
        on_duplicate: Literal["error", "ignore"] = "error",
        on_missing: Literal["error", "ignore"] = "error",
        model_id: str | None = None,
    ) -> WriteResult:
        preconditions = [
            {"tuple_key": as_key(t).model_dump(), "must_exist": True} for t in must_exist
        ] + [{"tuple_key": as_key(t).model_dump(), "must_exist": False} for t in must_not_exist]
        body: dict[str, Any] = {
            "writes": [as_key(t).model_dump() for t in writes],
            "deletes": [as_key(t).model_dump() for t in deletes],
            "preconditions": preconditions,
            "on_duplicate": on_duplicate,
            "on_missing": on_missing,
        }
        if model_id:
            body["model_id"] = model_id
        repeatable = on_duplicate == "ignore" and on_missing == "ignore" and not preconditions
        result = await self._request(
            "POST",
            f"/v1/stores/{self.store_id}/tuples/write",
            WriteResult,
            json=body,
            idempotent=repeatable,
        )
        self._remember(result.revision, result.consistency_token)
        return result

    async def read(
        self,
        *,
        object_type: str | None = None,
        object_id: str | None = None,
        relation: str | None = None,
        user: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> TuplePage:
        return await self._request(
            "GET",
            f"/v1/stores/{self.store_id}/tuples",
            TuplePage,
            params={
                "object_type": object_type,
                "object_id": object_id,
                "relation": relation,
                "user": user,
                "limit": limit,
                "cursor": cursor,
                "consistency_token": self.last_token() if self._read_your_writes else None,
            },
        )

    async def check(
        self,
        object: str,  # noqa: A002
        relation: str,
        user: str,
        *,
        contextual_tuples: Sequence[TupleLike] = (),
        consistency: Consistency | None = None,
        explain: bool = False,
        model_id: str | None = None,
    ) -> CheckResult:
        body: dict[str, Any] = {
            "tuple_key": TupleKey(object=object, relation=relation, user=user).model_dump(),
            "contextual_tuples": [as_key(t).model_dump() for t in contextual_tuples],
            "explain": explain,
            "consistency": self._consistency(consistency),
            "model_id": model_id,
        }
        return await self._request(
            "POST", f"/v1/stores/{self.store_id}/check", CheckResult, json=body, idempotent=True
        )

    async def batch_check(
        self,
        checks: Mapping[str, TupleLike],
        *,
        contextual_tuples: Sequence[TupleLike] = (),
        consistency: Consistency | None = None,
    ) -> dict[str, bool]:
        """Run several checks against one snapshot. Keys are caller-chosen correlation ids.

        Raises WardenBatchCheckError if any item could not be decided, so an error is
        never mistaken for a denial. Use batch_check_items to handle items one by one.
        """
        items = await self.batch_check_items(
            checks, contextual_tuples=contextual_tuples, consistency=consistency
        )
        failed = {cid: item for cid, item in items.items() if item.error is not None}
        if failed:
            raise WardenBatchCheckError(failed)
        return {cid: item.allowed for cid, item in items.items()}

    async def batch_check_items(
        self,
        checks: Mapping[str, TupleLike],
        *,
        contextual_tuples: Sequence[TupleLike] = (),
        consistency: Consistency | None = None,
    ) -> dict[str, BatchCheckItem]:
        body = {
            "checks": [
                {"tuple_key": as_key(t).model_dump(), "correlation_id": cid}
                for cid, t in checks.items()
            ],
            "contextual_tuples": [as_key(t).model_dump() for t in contextual_tuples],
            "consistency": self._consistency(consistency),
        }
        result = await self._request(
            "POST",
            f"/v1/stores/{self.store_id}/batch-check",
            BatchCheckResult,
            json=body,
            idempotent=True,
        )
        return {item.correlation_id or "": item for item in result.results}

    async def expand(
        self,
        object: str,  # noqa: A002
        relation: str,
        *,
        consistency: Consistency | None = None,
    ) -> ExpandResult:
        body = {
            "object": object,
            "relation": relation,
            "consistency": self._consistency(consistency),
        }
        return await self._request(
            "POST", f"/v1/stores/{self.store_id}/expand", ExpandResult, json=body, idempotent=True
        )

    async def list_objects(
        self,
        object_type: str,
        relation: str,
        user: str,
        *,
        contextual_tuples: Sequence[TupleLike] = (),
        consistency: Consistency | None = None,
        limit: int | None = None,
    ) -> ListObjectsResult:
        body = {
            "object_type": object_type,
            "relation": relation,
            "user": user,
            "contextual_tuples": [as_key(t).model_dump() for t in contextual_tuples],
            "consistency": self._consistency(consistency),
            "limit": limit,
        }
        return await self._request(
            "POST",
            f"/v1/stores/{self.store_id}/list-objects",
            ListObjectsResult,
            json=body,
            idempotent=True,
        )

    async def list_users(
        self,
        object: str,  # noqa: A002
        relation: str,
        user_type: str,
        *,
        contextual_tuples: Sequence[TupleLike] = (),
        consistency: Consistency | None = None,
    ) -> ListUsersResult:
        body = {
            "object": object,
            "relation": relation,
            "user_type": user_type,
            "contextual_tuples": [as_key(t).model_dump() for t in contextual_tuples],
            "consistency": self._consistency(consistency),
        }
        return await self._request(
            "POST",
            f"/v1/stores/{self.store_id}/list-users",
            ListUsersResult,
            json=body,
            idempotent=True,
        )


def _error(response: httpx.Response) -> WardenError:
    cls = error_for(response.status_code)
    try:
        payload = ErrorPayload.model_validate(response.json()["error"])
    except (ValueError, KeyError, TypeError):
        return cls(response.status_code, "http_error", response.text[:200])
    return cls(response.status_code, payload.code, payload.message, payload.details)
