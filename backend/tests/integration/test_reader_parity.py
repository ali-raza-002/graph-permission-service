"""The Postgres reader must answer exactly like the in-memory reader at every revision."""

from __future__ import annotations

import asyncio

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.property.strategies import OBJECT_IDS, TUPLESET, USERS, models, tuple_sets
from warden.core.refs import ObjectRef, RelationTuple, SubjectRef
from warden.db.database import Database
from warden.dsl import TypeSystem
from warden.engine.check import Checker
from warden.engine.reader import MemoryTupleReader, TupleReader
from warden.model.repository import StoreRepository
from warden.tuples.repository import PostgresTupleReader, TupleRepository


async def _answers(ts: TypeSystem, reader: TupleReader) -> dict[str, bool]:
    checker = Checker(ts, reader, max_depth=100)
    out: dict[str, bool] = {}
    for type_name in ts.type_names:
        if type_name == "user":
            continue
        for relation in ts.type_def(type_name).relations:
            if relation.name == TUPLESET:
                continue
            for object_id in OBJECT_IDS:
                for name in USERS:
                    obj, user = ObjectRef(type_name, object_id), SubjectRef("user", name)
                    key = f"{obj}#{relation.name}@{user}"
                    out[key] = (await checker.check(obj, relation.name, user)).allowed
    return out


async def _write(
    repo: TupleRepository,
    store_id: str,
    *,
    writes: list[RelationTuple],
    deletes: list[RelationTuple],
) -> int:
    outcome = await repo.write(
        store_id,
        writes=writes,
        deletes=deletes,
        preconditions=[],
        on_duplicate="error",
        on_missing="error",
    )
    return outcome.revision


@settings(
    max_examples=15,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.filter_too_much,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(data=st.data())
def test_postgres_snapshots_match_memory(database: str, data: st.DataObject) -> None:
    model = data.draw(models())
    first = data.draw(tuple_sets(model))
    removed = data.draw(st.lists(st.sampled_from(first), unique=True)) if first else []
    added = [t for t in data.draw(tuple_sets(model)) if t not in first]
    ts = TypeSystem(model)

    async def run() -> None:
        db = Database(database, pool_size=4, max_overflow=0)
        try:
            store = await StoreRepository(db).create("parity")
            repo = TupleRepository(db)
            rev1 = await _write(repo, store.id, writes=first, deletes=[])
            rev2 = await _write(repo, store.id, writes=added, deletes=removed)
            after: list[RelationTuple] = [t for t in first if t not in removed] + added

            for revision, expected_tuples in ((rev1, first), (rev2, after)):
                memory = await _answers(ts, MemoryTupleReader(expected_tuples))
                # Production prefetches whole object views for tupleset relations; the plain
                # reader issues one query per relation. Both must agree with memory.
                for tuplesets in (None, ts.tupleset_relations):
                    reader = PostgresTupleReader(db, store.id, revision, tuplesets=tuplesets)
                    pg = await _answers(ts, reader)
                    label = "prefetching" if tuplesets else "plain"
                    assert pg == memory, f"{label} reader diverged at revision {revision}"
        finally:
            await db.dispose()

    asyncio.run(run())
