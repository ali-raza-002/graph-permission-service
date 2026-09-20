"""Consistency tokens (Zanzibar calls them zookies).

A token encodes the store revision produced by a write. Passing it back as
at_least_as_fresh guarantees the check observes that write, which closes the
"new enemy" window where a stale replica would still grant revoked access.
"""

from __future__ import annotations

import base64
import binascii
from enum import StrEnum

from pydantic import BaseModel, model_validator

from warden.core.errors import InvalidConsistencyTokenError

TOKEN_PREFIX = "zk1."


class ConsistencyMode(StrEnum):
    MINIMIZE_LATENCY = "minimize_latency"
    AT_LEAST_AS_FRESH = "at_least_as_fresh"
    AT_EXACT_SNAPSHOT = "at_exact_snapshot"
    FULLY_CONSISTENT = "fully_consistent"


class Consistency(BaseModel):
    mode: ConsistencyMode = ConsistencyMode.MINIMIZE_LATENCY
    token: str | None = None

    @model_validator(mode="after")
    def _token_required(self) -> Consistency:
        needs_token = {ConsistencyMode.AT_LEAST_AS_FRESH, ConsistencyMode.AT_EXACT_SNAPSHOT}
        if self.mode in needs_token and not self.token:
            raise ValueError(f"consistency mode '{self.mode}' requires a token")
        return self


def encode_token(store_id: str, revision: int) -> str:
    raw = f"{store_id}:{revision}".encode()
    return TOKEN_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_token(token: str, store_id: str) -> int:
    if not token.startswith(TOKEN_PREFIX):
        raise InvalidConsistencyTokenError("consistency token is malformed")
    body = token[len(TOKEN_PREFIX) :]
    try:
        decoded = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode()
        token_store, _, revision = decoded.rpartition(":")
        value = int(revision)
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise InvalidConsistencyTokenError("consistency token is malformed") from None
    if token_store != store_id:
        raise InvalidConsistencyTokenError("consistency token was issued for a different store")
    if value < 0:
        raise InvalidConsistencyTokenError("consistency token is malformed")
    return value
