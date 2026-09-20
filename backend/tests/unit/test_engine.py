from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest

from tests.helpers import reader_of
from warden.cache.backends import MemoryCache
from warden.core.errors import ResolutionTooComplexError
from warden.core.refs import ObjectRef, RelationTuple, SubjectRef
from warden.dsl import TypeSystem, compile_model
from warden.engine.check import Checker, Outcome, race
from warden.engine.expand import Expander, tree_contains
from warden.engine.listing import ObjectLister, UserLister
from warden.engine.reader import ContextualTupleReader, MemoryTupleReader
from warden.engine.trace import TraceNode

TUPLES = [
    "group:eng#member@user:anne",
    "group:eng#member@group:leads#member",
    "group:leads#member@user:beth",
    "folder:root#editor@group:eng#member",
    "folder:plans#parent@folder:root",
    "folder:public#viewer@user:*",
    "document:roadmap#parent@folder:plans",
    "document:roadmap#owner@user:carl",
    "document:roadmap#editor@user:carl",
    "document:roadmap#blocked@user:anne",
    "document:memo#parent@folder:public",
    "document:memo#owner@user:dana",
]


def obj(raw: str) -> ObjectRef:
    return ObjectRef.parse(raw)


def user(raw: str) -> SubjectRef:
    return SubjectRef.parse(raw)


async def allowed(
    ts: TypeSystem, o: str, relation: str, u: str, tuples: Sequence[str] = TUPLES
) -> bool:
    return (await Checker(ts, reader_of(tuples)).check(obj(o), relation, user(u))).allowed


@pytest.mark.parametrize(
    ("o", "relation", "u", "expected"),
    [
        ("document:roadmap", "owner", "user:carl", True),
        ("document:roadmap", "owner", "user:anne", False),
        ("group:eng", "member", "user:beth", True),
        ("document:roadmap", "editor", "user:beth", True),
        ("document:roadmap", "viewer", "user:beth", True),
        ("document:roadmap", "viewer", "user:anne", False),
        ("document:roadmap", "editor", "user:anne", True),
        ("document:roadmap", "can_share", "user:carl", True),
        ("document:roadmap", "can_share", "user:beth", False),
        ("document:memo", "viewer", "user:zoe", True),
        ("document:memo", "editor", "user:zoe", False),
        ("document:roadmap", "viewer", "group:eng#member", True),
        ("group:eng", "member", "group:eng#member", True),
    ],
)
async def test_check(
    workspace_ts: TypeSystem, o: str, relation: str, u: str, expected: bool
) -> None:
    assert await allowed(workspace_ts, o, relation, u) is expected


async def test_tuples_outside_type_restrictions_are_ignored(workspace_ts: TypeSystem) -> None:
    tuples = ["document:x#owner@group:eng#member", "group:eng#member@user:anne"]
    assert not await allowed(workspace_ts, "document:x", "owner", "user:anne", tuples)


async def test_trace_explains_grant_path(workspace_ts: TypeSystem) -> None:
    outcome = await Checker(workspace_ts, reader_of(TUPLES)).check(
        obj("document:roadmap"), "editor", user("user:beth")
    )
    assert outcome.allowed

    def tuples_on_allowed_path(node: TraceNode) -> list[str]:
        found = [node.tuple_key] if node.tuple_key and node.result == "allowed" else []
        for child in node.children:
            if child.result == "allowed":
                found.extend(tuples_on_allowed_path(child))
        return found

    assert tuples_on_allowed_path(outcome.trace) == [
        "document:roadmap#parent@folder:plans",
        "folder:plans#parent@folder:root",
        "folder:root#editor@group:eng#member",
        "group:eng#member@group:leads#member",
        "group:leads#member@user:beth",
    ]


async def test_exclusion_trace_marks_roles(workspace_ts: TypeSystem) -> None:
    outcome = await Checker(workspace_ts, reader_of(TUPLES)).check(
        obj("document:roadmap"), "viewer", user("user:anne")
    )
    exclusion = outcome.trace.children[0]
    assert exclusion.kind == "exclusion"
    assert [c.role for c in exclusion.children] == ["base", "subtract"]
    assert exclusion.children[1].result == "allowed"


async def test_cycles_terminate_and_are_reported() -> None:
    ts = TypeSystem(
        compile_model(
            "type user\ntype folder\n  relations\n"
            "    define parent: [folder]\n    define viewer: [user] or viewer from parent\n"
        )
    )
    reader = reader_of(["folder:a#parent@folder:b", "folder:b#parent@folder:a"])
    outcome = await Checker(ts, reader).check(obj("folder:a"), "viewer", user("user:x"))
    assert not outcome.allowed

    def kinds(node: TraceNode) -> set[str]:
        return {node.kind}.union(*(kinds(c) for c in node.children))

    assert "cycle" in kinds(outcome.trace)


GROUP_MODEL = "type user\ntype group\n  relations\n    define member: [user, group#member]\n"


async def test_dense_cyclic_graphs_resolve_in_linear_work() -> None:
    """Twelve groups that all contain each other have ~10^8 simple paths between them.
    Sharing sub-problems keeps the work proportional to the number of groups."""
    ts = TypeSystem(compile_model(GROUP_MODEL))
    groups = [f"g{i}" for i in range(12)]
    tuples = [f"group:{a}#member@group:{b}#member" for a in groups for b in groups if a != b]
    checker = Checker(ts, reader_of([*tuples, "group:g11#member@user:zoe"]))
    assert (await checker.check(obj("group:g0"), "member", user("user:zoe"))).allowed

    denied = Checker(ts, reader_of(tuples))
    assert not (await denied.check(obj("group:g0"), "member", user("user:zoe"))).allowed
    assert denied.stats.dispatches <= len(groups) * denied.stats.passes


async def test_mutual_dependency_needs_a_second_pass() -> None:
    """y holds through a cycle that is cut while x waits on both branches; the first
    pass assumes 'denied' for the cut and the second pass corrects it."""
    ts = TypeSystem(
        compile_model(
            "type user\ntype doc\n  relations\n"
            "    define y: [user] or z\n    define z: y\n    define x: y and z\n"
        )
    )
    checker = Checker(ts, reader_of(["doc:a#y@user:u"]))
    assert (await checker.check(obj("doc:a"), "x", user("user:u"))).allowed


async def test_depth_limit_raises() -> None:
    ts = TypeSystem(
        compile_model(
            "type user\ntype folder\n  relations\n"
            "    define parent: [folder]\n    define viewer: [user] or viewer from parent\n"
        )
    )
    chain = [f"folder:f{i}#parent@folder:f{i + 1}" for i in range(40)]
    with pytest.raises(ResolutionTooComplexError):
        await Checker(ts, reader_of(chain), max_depth=10).check(
            obj("folder:f0"), "viewer", user("user:x")
        )
    deep_enough = Checker(ts, reader_of([*chain, "folder:f40#viewer@user:x"]), max_depth=100)
    assert (await deep_enough.check(obj("folder:f0"), "viewer", user("user:x"))).allowed


async def test_contextual_tuples_layer_over_snapshot(workspace_ts: TypeSystem) -> None:
    contextual = [RelationTuple.parse("group:eng#member@user:zoe")]
    reader = ContextualTupleReader(reader_of(TUPLES), contextual)
    outcome = await Checker(workspace_ts, reader).check(
        obj("document:roadmap"), "editor", user("user:zoe")
    )
    assert outcome.allowed
    assert not await allowed(workspace_ts, "document:roadmap", "editor", "user:zoe")


async def test_shared_cache_is_used_across_checkers(workspace_ts: TypeSystem) -> None:
    cache = MemoryCache(max_entries=1000, ttl_seconds=60)
    reader = reader_of(TUPLES)
    first = Checker(workspace_ts, reader, cache=cache, cache_namespace="s:m:1:")
    await first.check(obj("document:roadmap"), "viewer", user("user:beth"))
    second = Checker(workspace_ts, MemoryTupleReader(), cache=cache, cache_namespace="s:m:1:")
    outcome = await second.check(obj("document:roadmap"), "viewer", user("user:beth"))
    assert outcome.allowed
    assert outcome.trace.cached
    other_revision = Checker(
        workspace_ts, MemoryTupleReader(), cache=cache, cache_namespace="s:m:2:"
    )
    assert not (
        await other_revision.check(obj("document:roadmap"), "viewer", user("user:beth"))
    ).allowed


async def test_explain_mode_bypasses_cache_reads(workspace_ts: TypeSystem) -> None:
    cache = MemoryCache(max_entries=1000, ttl_seconds=60)
    reader = reader_of(TUPLES)
    await Checker(workspace_ts, reader, cache=cache).check(
        obj("document:roadmap"), "viewer", user("user:beth")
    )
    explained = await Checker(workspace_ts, reader, cache=cache, read_from_cache=False).check(
        obj("document:roadmap"), "viewer", user("user:beth")
    )
    assert not explained.trace.cached
    assert explained.trace.children


async def test_race_short_circuits_and_cancels_slow_children() -> None:
    cancelled = asyncio.Event()

    async def fast() -> Outcome:
        return Outcome(True, TraceNode(kind="check", label="fast", result="allowed"))

    async def slow() -> Outcome:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return Outcome(False, TraceNode(kind="check", label="slow", result="denied"))

    results, stopper = await race([slow(), fast()], lambda _i, r: r.allowed)
    assert stopper == 1
    assert results[0] is None
    assert cancelled.is_set()


async def test_expand_matches_check(workspace_ts: TypeSystem) -> None:
    reader = reader_of(TUPLES)
    tree = await Expander(workspace_ts, reader).expand(obj("document:roadmap"), "viewer")
    for name in ["anne", "beth", "carl", "dana", "zoe"]:
        expected = await allowed(workspace_ts, "document:roadmap", "viewer", f"user:{name}")
        assert tree_contains(tree, user(f"user:{name}")) is expected


async def test_list_objects(workspace_ts: TypeSystem) -> None:
    reader = reader_of(TUPLES)
    lister = ObjectLister(workspace_ts, reader, Checker(workspace_ts, reader))
    assert [str(o) for o in await lister.list_objects("document", "viewer", user("user:beth"))] == [
        "document:memo",
        "document:roadmap",
    ]
    assert [str(o) for o in await lister.list_objects("document", "viewer", user("user:anne"))] == [
        "document:memo"
    ]
    assert await lister.list_objects("document", "can_share", user("user:beth")) == []


async def test_list_users_respects_exclusion(workspace_ts: TypeSystem) -> None:
    reader = reader_of(TUPLES)
    lister = UserLister(
        workspace_ts, reader, Checker(workspace_ts, reader), Expander(workspace_ts, reader)
    )
    users = await lister.list_users(obj("document:roadmap"), "viewer", "user")
    assert [str(u) for u in users] == ["user:beth", "user:carl"]
    groups = await lister.list_users(obj("document:roadmap"), "editor", "group", "member")
    assert [str(g) for g in groups] == ["group:eng#member", "group:leads#member"]


async def test_one_expander_serves_concurrent_requests(workspace_ts: TypeSystem) -> None:
    expander = Expander(workspace_ts, reader_of(TUPLES))
    alone = await expander.expand(obj("document:roadmap"), "viewer")
    together = await asyncio.gather(
        *(expander.expand(obj("document:roadmap"), "viewer") for _ in range(8)),
        *(expander.expand(obj("document:memo"), "viewer") for _ in range(8)),
    )
    assert all(tree == alone for tree in together[:8])
    assert all(tree_contains(t, user("user:dana")) for t in together[8:])


async def test_repeated_sub_problems_are_marked_memoized_not_cached() -> None:
    ts = TypeSystem(
        compile_model(
            "type user\ntype doc\n  relations\n    define owner: [user]\n"
            "    define a: owner\n    define b: owner\n    define both: a and b\n"
        )
    )
    checker = Checker(ts, reader_of(["doc:1#owner@user:anne"]))
    outcome = await checker.check(obj("doc:1"), "both", user("user:anne"))
    assert outcome.allowed

    def owners(node: TraceNode) -> list[TraceNode]:
        found = [node] if node.label == "doc:1#owner" and node.kind == "check" else []
        return found + [n for c in node.children for n in owners(c)]

    first, repeat = owners(outcome.trace)
    assert (first.memoized, first.cached, bool(first.children)) == (False, False, True)
    assert (repeat.memoized, repeat.cached, repeat.children) == (True, False, [])


async def test_list_objects_stops_at_the_limit() -> None:
    ts = TypeSystem(compile_model("type user\ntype doc\n  relations\n    define viewer: [user]\n"))
    reader = reader_of([f"doc:{n:02d}#viewer@user:anne" for n in range(40)])
    checker = Checker(ts, reader)
    lister = ObjectLister(ts, reader, checker, concurrency=8)

    first = await lister.find("doc", "viewer", user("user:anne"), limit=5)
    assert [o.id for o in first.items] == ["00", "01", "02", "03", "04"]
    assert first.truncated
    assert checker.stats.dispatches <= 8, "only the first wave of candidates is confirmed"

    everything = await lister.find("doc", "viewer", user("user:anne"), limit=40)
    assert (len(everything.items), everything.truncated) == (40, False)
    capped = ObjectLister(ts, reader, Checker(ts, reader), max_candidates=10)
    assert (await capped.find("doc", "viewer", user("user:anne"))).truncated


async def test_failed_branch_cancels_its_siblings() -> None:
    ts = TypeSystem(
        compile_model(
            "type user\ntype doc\n  relations\n    define parent: [doc]\n"
            "    define viewer: [user] or viewer from parent\n"
        )
    )
    chain = [f"doc:{n}#parent@doc:{n + 1}" for n in range(30)]
    checker = Checker(ts, reader_of(chain), max_depth=10)
    before = asyncio.all_tasks()
    with pytest.raises(ResolutionTooComplexError):
        await checker.check(obj("doc:0"), "viewer", user("user:anne"))
    orphans = [t for t in asyncio.all_tasks() - before if not t.done()]
    assert orphans == [], "no orphaned sub-checks keep running"
