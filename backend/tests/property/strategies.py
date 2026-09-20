"""Hypothesis strategies for random authorization models and tuple sets.

Exclusions only ever subtract a direct set of users. That keeps every recursive path
monotone, so the model has a unique least fixpoint that an independent naive
evaluator can compute and the engine must agree with.
"""

from __future__ import annotations

from itertools import product

from hypothesis import assume
from hypothesis import strategies as st

from warden.core.refs import ObjectRef, RelationTuple, SubjectRef
from warden.dsl import AuthorizationModel, TypeSystem, validate_model
from warden.dsl.ast import (
    ComputedNode,
    DirectNode,
    ExclusionNode,
    IntersectionNode,
    RelationDef,
    Rewrite,
    TupleToUsersetNode,
    TypeDef,
    TypeRestriction,
    UnionNode,
)
from warden.dsl.typesystem import restriction_allows

OBJECT_TYPES = ("doc", "folder")
OBJECT_IDS = ("a", "b", "c")
USERS = ("u0", "u1", "u2")
TUPLESET = "parent"


def _rewrites(types: tuple[str, ...], relations: tuple[str, ...]) -> st.SearchStrategy[Rewrite]:
    restriction = st.one_of(
        st.just(TypeRestriction(type="user")),
        st.just(TypeRestriction(type="user", wildcard=True)),
        st.builds(
            lambda t, r: TypeRestriction(type=t, relation=r),
            st.sampled_from(types),
            st.sampled_from(relations),
        ),
    )
    direct = st.lists(restriction, min_size=1, max_size=3, unique=True).map(
        lambda rs: DirectNode(types=tuple(rs))
    )
    computed = st.sampled_from(relations).map(lambda r: ComputedNode(relation=r))
    ttu = st.sampled_from(relations).map(
        lambda r: TupleToUsersetNode(tupleset=TUPLESET, computed=r)
    )
    subtract = st.just(DirectNode(types=(TypeRestriction(type="user"),)))

    def extend(inner: st.SearchStrategy[Rewrite]) -> st.SearchStrategy[Rewrite]:
        return st.one_of(
            st.lists(inner, min_size=2, max_size=3).map(lambda cs: UnionNode(children=tuple(cs))),
            st.lists(inner, min_size=2, max_size=2).map(
                lambda cs: IntersectionNode(children=tuple(cs))
            ),
            st.tuples(inner, subtract).map(lambda p: ExclusionNode(base=p[0], subtract=p[1])),
        )

    return st.recursive(st.one_of(direct, computed, ttu), extend, max_leaves=5)


@st.composite
def models(draw: st.DrawFn) -> AuthorizationModel:
    types = OBJECT_TYPES[: draw(st.integers(1, len(OBJECT_TYPES)))]
    relations = tuple(f"r{i}" for i in range(draw(st.integers(1, 3))))
    rewrites = _rewrites(types, relations)
    type_defs = [TypeDef(name="user")]
    for type_name in types:
        parents = draw(st.lists(st.sampled_from(types), min_size=1, unique=True))
        defs = [
            RelationDef(
                name=TUPLESET,
                rewrite=DirectNode(types=tuple(TypeRestriction(type=p) for p in parents)),
            )
        ]
        defs.extend(RelationDef(name=r, rewrite=draw(rewrites)) for r in relations)
        type_defs.append(TypeDef(name=type_name, relations=tuple(defs)))
    model = AuthorizationModel(types=tuple(type_defs))
    assume(not [i for i in validate_model(model) if i.severity == "error"])
    return model


def _candidate_tuples(ts: TypeSystem) -> list[RelationTuple]:
    out: list[RelationTuple] = []
    for type_name in ts.type_names:
        for relation in ts.type_def(type_name).relations:
            for restriction, object_id in product(
                ts.direct_restrictions(type_name, relation.name), OBJECT_IDS
            ):
                if restriction.wildcard:
                    subjects = [SubjectRef(restriction.type, "*")]
                elif restriction.type == "user":
                    subjects = [SubjectRef("user", u) for u in USERS]
                else:
                    subjects = [
                        SubjectRef(restriction.type, i, restriction.relation) for i in OBJECT_IDS
                    ]
                out.extend(
                    RelationTuple(ObjectRef(type_name, object_id), relation.name, s)
                    for s in subjects
                )
    return out


@st.composite
def tuple_sets(draw: st.DrawFn, model: AuthorizationModel) -> list[RelationTuple]:
    candidates = _candidate_tuples(TypeSystem(model))
    size = min(len(candidates), 40)
    return draw(
        st.lists(st.sampled_from(candidates), min_size=min(size, 10), max_size=size, unique=True)
    )


def least_fixpoint(
    ts: TypeSystem, tuples: list[RelationTuple]
) -> set[tuple[ObjectRef, str, SubjectRef]]:
    """Naive bottom-up evaluation: iterate every (object, relation, user) until stable."""
    by_key: dict[tuple[ObjectRef, str], list[SubjectRef]] = {}
    for t in tuples:
        by_key.setdefault((t.object, t.relation), []).append(t.subject)
    objects = [ObjectRef(t, i) for t in ts.type_names if t != "user" for i in OBJECT_IDS]
    users = [SubjectRef("user", u) for u in USERS]
    facts: set[tuple[ObjectRef, str, SubjectRef]] = set()

    def holds(node: Rewrite, obj: ObjectRef, relation: str, user: SubjectRef) -> bool:
        match node:
            case DirectNode(types=restrictions):
                for s in by_key.get((obj, relation), ()):
                    if not any(restriction_allows(r, s) for r in restrictions):
                        continue
                    if s == user or (s.is_wildcard and s.type == user.type):
                        return True
                    if s.relation and (s.as_object(), s.relation, user) in facts:
                        return True
                return False
            case ComputedNode(relation=target):
                return (obj, target, user) in facts
            case TupleToUsersetNode(tupleset=tupleset, computed=computed):
                allowed = ts.direct_restrictions(obj.type, tupleset)
                return any(
                    (p.as_object(), computed, user) in facts
                    for p in by_key.get((obj, tupleset), ())
                    if p.relation is None
                    and not p.is_wildcard
                    and any(restriction_allows(r, p) for r in allowed)
                    and ts.has_relation(p.type, computed)
                )
            case UnionNode(children=children):
                return any(holds(c, obj, relation, user) for c in children)
            case IntersectionNode(children=children):
                return all(holds(c, obj, relation, user) for c in children)
            case ExclusionNode(base=base, subtract=subtract):
                return holds(base, obj, relation, user) and not holds(subtract, obj, relation, user)

    changed = True
    while changed:
        changed = False
        for obj in objects:
            for relation in ts.type_def(obj.type).relations:
                for user in users:
                    fact = (obj, relation.name, user)
                    if fact not in facts and holds(relation.rewrite, obj, relation.name, user):
                        facts.add(fact)
                        changed = True
    return facts
