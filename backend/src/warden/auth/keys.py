from __future__ import annotations

import hashlib
import hmac
import secrets
import string
import time
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update

from warden.core.errors import (
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from warden.core.ids import new_id
from warden.db.database import Database
from warden.db.tables import ApiKeyRow

KEY_PREFIX = "wdn"
_ALPHABET = string.ascii_lowercase + string.digits


class Scope(StrEnum):
    KEYS_ADMIN = "keys:admin"
    STORES_ADMIN = "stores:admin"
    MODELS_READ = "models:read"
    MODELS_WRITE = "models:write"
    TUPLES_READ = "tuples:read"
    TUPLES_WRITE = "tuples:write"
    CHECK = "check"
    DECISIONS_READ = "decisions:read"


ALL_SCOPES = frozenset(Scope)
_GLOBAL_SCOPES = frozenset({Scope.KEYS_ADMIN, Scope.STORES_ADMIN})


@dataclass(frozen=True, slots=True)
class Principal:
    key_id: str | None
    name: str
    scopes: frozenset[Scope]
    store_id: str | None

    def authorize(self, scope: Scope, store_id: str | None = None) -> None:
        if scope not in self.scopes:
            raise PermissionDeniedError(f"API key '{self.name}' lacks the '{scope}' scope")
        if self.store_id is not None and store_id is not None and store_id != self.store_id:
            raise PermissionDeniedError(f"API key '{self.name}' is limited to another store")
        if self.store_id is not None and store_id is None and scope in _GLOBAL_SCOPES:
            raise PermissionDeniedError("store-scoped keys cannot manage stores or keys")


class ApiKey(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    prefix: str
    scopes: list[Scope]
    store_id: str | None
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class CreatedApiKey(ApiKey):
    key: str = Field(description="The plaintext key. It is shown once and never stored.")


def _hash(raw: str) -> str:
    # Keys carry ~190 bits of entropy, so a fast hash is sufficient; a password KDF
    # would only add latency to every request.
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_key() -> tuple[str, str]:
    prefix = "".join(secrets.choice(_ALPHABET) for _ in range(8))
    secret = secrets.token_urlsafe(24)
    return prefix, f"{KEY_PREFIX}_{prefix}_{secret}"


class _PrincipalCache:
    """Bounded TTL cache of authenticated keys.

    Revocation only clears the replica that served it, so other replicas keep accepting
    a revoked key for up to `ttl` seconds. Set the TTL to 0 to trade that window for a
    database lookup on every request.
    """

    def __init__(self, *, ttl: float, max_entries: int) -> None:
        self._ttl = ttl
        self._max = max_entries
        self._entries: OrderedDict[str, tuple[Principal, float]] = OrderedDict()

    def get(self, digest: str) -> Principal | None:
        entry = self._entries.get(digest)
        if entry is None:
            return None
        if time.monotonic() - entry[1] >= self._ttl:
            del self._entries[digest]
            return None
        self._entries.move_to_end(digest)
        return entry[0]

    def put(self, digest: str, principal: Principal) -> None:
        if self._ttl <= 0:
            return
        self._entries[digest] = (principal, time.monotonic())
        self._entries.move_to_end(digest)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)

    def evict_key(self, key_id: str) -> None:
        for digest in [d for d, (p, _) in self._entries.items() if p.key_id == key_id]:
            del self._entries[digest]

    def __len__(self) -> int:
        return len(self._entries)


class ApiKeyService:
    def __init__(
        self,
        db: Database,
        *,
        bootstrap_key: str | None,
        cache_ttl_seconds: float = 30.0,
        cache_max_entries: int = 10_000,
    ) -> None:
        self._db = db
        self._bootstrap = bootstrap_key
        self._principals = _PrincipalCache(ttl=cache_ttl_seconds, max_entries=cache_max_entries)

    async def create(
        self,
        *,
        name: str,
        scopes: Sequence[Scope],
        store_id: str | None,
        preshared: str | None = None,
    ) -> CreatedApiKey:
        """Create a key. `preshared` imports an operator-provided key (used by provisioning
        scripts) instead of generating one."""
        if store_id is not None and _GLOBAL_SCOPES.intersection(scopes):
            raise PermissionDeniedError(
                "store-scoped keys cannot hold the stores:admin or keys:admin scopes"
            )
        if preshared is not None:
            parts = preshared.split("_", 2)
            if len(parts) != 3 or parts[0] != KEY_PREFIX or len(parts[2]) < 16:
                raise ValidationFailedError("preshared keys must look like wdn_<prefix>_<secret>")
            prefix, raw = parts[1], preshared
        else:
            prefix, raw = generate_key()
        row = ApiKeyRow(
            id=new_id("key"),
            store_id=store_id,
            name=name,
            prefix=prefix,
            key_hash=_hash(raw),
            scopes=sorted({s.value for s in scopes}),
        )
        async with self._db.transaction() as session:
            session.add(row)
            await session.flush()
            await session.refresh(row)
        return CreatedApiKey(**ApiKey.model_validate(row).model_dump(), key=raw)

    async def page(self, *, store_id: str | None) -> list[ApiKey]:
        stmt = select(ApiKeyRow).order_by(ApiKeyRow.created_at.desc())
        if store_id is not None:
            stmt = stmt.where(ApiKeyRow.store_id == store_id)
        async with self._db.session() as session:
            return [ApiKey.model_validate(r) for r in (await session.scalars(stmt)).all()]

    async def revoke(self, key_id: str, *, store_id: str | None) -> None:
        stmt = update(ApiKeyRow).where(ApiKeyRow.id == key_id, ApiKeyRow.revoked_at.is_(None))
        if store_id is not None:
            stmt = stmt.where(ApiKeyRow.store_id == store_id)
        async with self._db.transaction() as session:
            result = await session.execute(stmt.values(revoked_at=func.now()))
        if not getattr(result, "rowcount", 0):
            raise NotFoundError(f"API key '{key_id}' does not exist")
        self._principals.evict_key(key_id)

    async def authenticate(self, raw: str) -> Principal:
        if self._bootstrap and hmac.compare_digest(raw.encode(), self._bootstrap.encode()):
            return Principal(key_id=None, name="bootstrap", scopes=ALL_SCOPES, store_id=None)

        digest = _hash(raw)
        cached = self._principals.get(digest)
        if cached is not None:
            return cached

        parts = raw.split("_", 2)
        if len(parts) != 3 or parts[0] != KEY_PREFIX:
            raise AuthenticationError("API key is malformed")
        async with self._db.transaction() as session:
            row = (
                await session.scalars(select(ApiKeyRow).where(ApiKeyRow.prefix == parts[1]))
            ).one_or_none()
            if (
                row is None
                or row.revoked_at is not None
                or not hmac.compare_digest(row.key_hash, digest)
            ):
                raise AuthenticationError("API key is invalid or revoked")
            row.last_used_at = datetime.now(UTC)
            principal = Principal(
                key_id=row.id,
                name=row.name,
                scopes=frozenset(Scope(s) for s in row.scopes if s in Scope._value2member_map_),
                store_id=row.store_id,
            )
        self._principals.put(digest, principal)
        return principal
