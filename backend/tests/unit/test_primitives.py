from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from warden.cache.backends import MemoryCache
from warden.config import Settings
from warden.core.consistency import Consistency, ConsistencyMode, decode_token, encode_token
from warden.core.errors import InvalidConsistencyTokenError
from warden.core.ids import new_id
from warden.core.pagination import InvalidCursorError, decode_int_cursor, encode_cursor
from warden.core.refs import ObjectRef, RefParseError, RelationTuple, SubjectRef
from warden.engine.trace import TraceNode, count_nodes, prune
from warden.tuples.schemas import TupleKey


def test_tuple_notation_round_trips() -> None:
    raw = "document:2024/q1-plan#viewer@group:eng#member"
    t = RelationTuple.parse(raw)
    assert t.object == ObjectRef("document", "2024/q1-plan")
    assert t.subject == SubjectRef("group", "eng", "member")
    assert str(t) == raw


def test_object_ids_may_contain_at_signs() -> None:
    raw = "mailbox:anne@lumen.dev#owner@user:anne@lumen.dev"
    t = RelationTuple.parse(raw)
    assert t.object == ObjectRef("mailbox", "anne@lumen.dev")
    assert t.subject == SubjectRef("user", "anne@lumen.dev")
    assert str(t) == raw


@pytest.mark.parametrize(
    "key",
    [
        "wdn_bootstrap_change-me-in-production",
        "wdn_bootstrap_local-dev-only-change-me-padding-to-32",
        "too-short",
    ],
)
def test_production_refuses_weak_bootstrap_keys(key: str) -> None:
    with pytest.raises(ValidationError, match="BOOTSTRAP_ADMIN_KEY"):
        Settings(_env_file=None, env="production", bootstrap_admin_key=SecretStr(key))


def test_production_accepts_strong_or_absent_bootstrap_keys() -> None:
    strong = Settings(
        _env_file=None, env="production", bootstrap_admin_key=SecretStr("wdn_ops_" + "k3y" * 12)
    )
    assert strong.env == "production"
    assert Settings(_env_file=None, env="production").bootstrap_admin_key is None
    local = Settings(_env_file=None, env="development", bootstrap_admin_key=SecretStr("change-me"))
    assert local.env == "development"


@pytest.mark.parametrize(
    "raw", ["document", "document:", ":x", "document:a b", "user:*#member", "doc:x#"]
)
def test_invalid_refs_are_rejected(raw: str) -> None:
    with pytest.raises(RefParseError):
        SubjectRef.parse(raw)


def test_tuple_key_validates_at_the_boundary() -> None:
    with pytest.raises(ValueError, match="not a valid subject"):
        TupleKey(object="document:x", relation="viewer", user="anne")
    assert (
        TupleKey(object="document:x", relation="viewer", user="user:*")
        .to_tuple()
        .subject.is_wildcard
    )


def test_consistency_token_round_trip() -> None:
    token = encode_token("st_abc", 42)
    assert decode_token(token, "st_abc") == 42


@pytest.mark.parametrize("token", ["nope", "zk1.!!!", "zk1." + "c3RfYWJjOng"])
def test_malformed_tokens(token: str) -> None:
    with pytest.raises(InvalidConsistencyTokenError):
        decode_token(token, "st_abc")


def test_tokens_are_bound_to_their_store() -> None:
    with pytest.raises(InvalidConsistencyTokenError, match="different store"):
        decode_token(encode_token("st_a", 1), "st_b")


def test_fresh_modes_require_a_token() -> None:
    with pytest.raises(ValueError, match="requires a token"):
        Consistency(mode=ConsistencyMode.AT_LEAST_AS_FRESH)


def test_cursor_round_trip_and_tamper_detection() -> None:
    assert decode_int_cursor(encode_cursor(17)) == 17
    with pytest.raises(InvalidCursorError):
        decode_int_cursor("garbage")
    with pytest.raises(InvalidCursorError):
        decode_int_cursor(encode_cursor("seventeen"))


def test_ids_are_prefixed_and_time_sortable() -> None:
    first, second = new_id("dec"), new_id("dec")
    assert first.startswith("dec_")
    assert len(first) == 30
    assert first[:14] <= second[:14]


async def test_memory_cache_evicts_least_recently_used() -> None:
    cache = MemoryCache(max_entries=2, ttl_seconds=60)
    await cache.set("a", True)
    await cache.set("b", False)
    assert await cache.get("a") is True
    await cache.set("c", True)
    assert await cache.get("b") is None
    assert await cache.get("a") is True
    assert cache.stats.hits == 2
    assert cache.stats.misses == 1


async def test_memory_cache_expires_entries() -> None:
    cache = MemoryCache(max_entries=10, ttl_seconds=-1)
    await cache.set("a", True)
    assert await cache.get("a") is None


def test_prune_keeps_allowed_branches_first() -> None:
    denied = [TraceNode(kind="check", label=f"d{i}", result="denied") for i in range(5)]
    allowed = TraceNode(kind="check", label="yes", result="allowed")
    root = TraceNode(kind="union", label="or", result="allowed", children=[*denied, allowed])
    pruned = prune(root, 3)
    assert count_nodes(pruned) == 3
    assert pruned.children[0].label == "yes"
