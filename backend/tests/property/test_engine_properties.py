from __future__ import annotations

import asyncio
import os

from hypothesis import HealthCheck, event, given, settings
from hypothesis import strategies as st

from tests.property.strategies import (
    OBJECT_IDS,
    TUPLESET,
    USERS,
    least_fixpoint,
    models,
    tuple_sets,
)
from warden.core.refs import ObjectRef, SubjectRef
from warden.dsl import AuthorizationModel, TypeSystem, compile_model, format_model, parse_model
from warden.engine.check import Checker
from warden.engine.expand import Expander, tree_contains
from warden.engine.listing import ObjectLister
from warden.engine.reader import MemoryTupleReader

PROFILE = settings(
    max_examples=int(os.environ.get("WARDEN_PROPERTY_EXAMPLES", "150")),
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)


@PROFILE
@given(data=st.data())
def test_check_expand_and_list_objects_agree_with_least_fixpoint(data: st.DataObject) -> None:
    model = data.draw(models())
    tuples = data.draw(tuple_sets(model))
    ts = TypeSystem(model)
    expected = least_fixpoint(ts, tuples)
    event(f"granted facts: {min(len(expected), 10)}{'+' if len(expected) >= 10 else ''}")

    async def verify() -> None:
        reader = MemoryTupleReader(tuples)
        checker = Checker(ts, reader, max_depth=100)
        expander = Expander(ts, reader, max_depth=100)
        lister = ObjectLister(ts, reader, Checker(ts, reader, max_depth=100))
        for type_name in ts.type_names:
            if type_name == "user":
                continue
            relations = [r.name for r in ts.type_def(type_name).relations if r.name != TUPLESET]
            for relation in relations:
                for object_id in OBJECT_IDS:
                    obj = ObjectRef(type_name, object_id)
                    tree = await expander.expand(obj, relation)
                    for name in USERS:
                        user = SubjectRef("user", name)
                        want = (obj, relation, user) in expected
                        got = (await checker.check(obj, relation, user)).allowed
                        assert got == want, f"check {obj}#{relation}@{user}: {got} != {want}"
                        assert tree_contains(tree, user) == want, (
                            f"expand {obj}#{relation} disagrees for {user}"
                        )
                for name in USERS:
                    user = SubjectRef("user", name)
                    listed = set(await lister.list_objects(type_name, relation, user))
                    want_objects = {
                        ObjectRef(type_name, i)
                        for i in OBJECT_IDS
                        if (ObjectRef(type_name, i), relation, user) in expected
                    }
                    assert listed == want_objects, f"list_objects {type_name}#{relation}@{user}"

    asyncio.run(verify())


@PROFILE
@given(model=models())
def test_formatting_is_a_fixed_point_and_preserves_validity(model: AuthorizationModel) -> None:
    text = format_model(model)
    reparsed = compile_model(text)
    assert format_model(reparsed) == text
    assert format_model(parse_model(text)) == text
