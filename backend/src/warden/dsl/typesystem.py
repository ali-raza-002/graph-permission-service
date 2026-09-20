from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cached_property

from warden.core.refs import RelationTuple, SubjectRef
from warden.dsl.ast import (
    AuthorizationModel,
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


def walk(rewrite: Rewrite, *, positive_only: bool = False) -> Iterator[Rewrite]:
    """Yield every node of a rewrite tree.

    With positive_only, the subtracted side of an exclusion is skipped: being in that
    set can only ever remove access, so it never contributes a path towards a grant.
    """
    yield rewrite
    match rewrite:
        case UnionNode(children=children) | IntersectionNode(children=children):
            for child in children:
                yield from walk(child, positive_only=positive_only)
        case ExclusionNode(base=base, subtract=subtract):
            yield from walk(base, positive_only=positive_only)
            if not positive_only:
                yield from walk(subtract, positive_only=positive_only)
        case _:
            pass


def restriction_allows(restriction: TypeRestriction, subject: SubjectRef) -> bool:
    if restriction.type != subject.type:
        return False
    if restriction.wildcard:
        return subject.is_wildcard
    if restriction.relation is not None:
        return subject.relation == restriction.relation and not subject.is_wildcard
    return subject.relation is None and not subject.is_wildcard


@dataclass(frozen=True, slots=True)
class TupleToUsersetEdge:
    """t2#relation is granted to parents' t#computed through tuples on t2#tupleset."""

    object_type: str
    relation: str
    tupleset: str


class UnknownRelationError(KeyError):
    pass


class TypeSystem:
    """Indexed, read-only view of an authorization model used by the engine."""

    def __init__(self, model: AuthorizationModel) -> None:
        self.model = model
        self._types: dict[str, TypeDef] = {t.name: t for t in model.types}
        self._relations: dict[tuple[str, str], RelationDef] = {
            (t.name, r.name): r for t in model.types for r in t.relations
        }
        self._direct: dict[tuple[str, str], tuple[TypeRestriction, ...]] = {}
        for key, relation in self._relations.items():
            restrictions: list[TypeRestriction] = []
            for node in walk(relation.rewrite):
                if isinstance(node, DirectNode):
                    restrictions.extend(r for r in node.types if r not in restrictions)
            self._direct[key] = tuple(restrictions)
        self._computed_dependents: dict[tuple[str, str], list[str]] = defaultdict(list)
        self._ttu_dependents: dict[tuple[str, str], list[TupleToUsersetEdge]] = defaultdict(list)
        self._userset_targets: set[tuple[str, str]] = set()
        self._index_reverse_edges()

    def _index_reverse_edges(self) -> None:
        for (type_name, relation_name), relation in self._relations.items():
            for node in walk(relation.rewrite, positive_only=True):
                match node:
                    case ComputedNode(relation=target):
                        deps = self._computed_dependents[(type_name, target)]
                        if relation_name not in deps:
                            deps.append(relation_name)
                    case TupleToUsersetNode(tupleset=tupleset, computed=computed):
                        edge = TupleToUsersetEdge(type_name, relation_name, tupleset)
                        for parent_type in self.tupleset_parent_types(type_name, tupleset):
                            deps_ttu = self._ttu_dependents[(parent_type, computed)]
                            if edge not in deps_ttu:
                                deps_ttu.append(edge)
                    case DirectNode(types=types):
                        for restriction in types:
                            if restriction.relation is not None:
                                self._userset_targets.add((restriction.type, restriction.relation))
                    case _:
                        pass

    @property
    def type_names(self) -> list[str]:
        return list(self._types)

    def has_type(self, name: str) -> bool:
        return name in self._types

    def has_relation(self, type_name: str, relation: str) -> bool:
        return (type_name, relation) in self._relations

    def type_def(self, name: str) -> TypeDef:
        return self._types[name]

    def relation(self, type_name: str, relation: str) -> RelationDef:
        try:
            return self._relations[(type_name, relation)]
        except KeyError:
            raise UnknownRelationError(
                f"relation '{type_name}#{relation}' is not defined"
            ) from None

    def direct_restrictions(self, type_name: str, relation: str) -> tuple[TypeRestriction, ...]:
        return self._direct.get((type_name, relation), ())

    def is_assignable(self, type_name: str, relation: str, subject: SubjectRef) -> bool:
        return any(
            restriction_allows(r, subject) for r in self.direct_restrictions(type_name, relation)
        )

    def tupleset_parent_types(self, type_name: str, tupleset: str) -> list[str]:
        return [
            r.type
            for r in self.direct_restrictions(type_name, tupleset)
            if r.relation is None and not r.wildcard
        ]

    def computed_dependents(self, type_name: str, relation: str) -> list[str]:
        return self._computed_dependents.get((type_name, relation), [])

    def ttu_dependents(self, type_name: str, relation: str) -> list[TupleToUsersetEdge]:
        return self._ttu_dependents.get((type_name, relation), [])

    @cached_property
    def tupleset_relations(self) -> dict[str, frozenset[str]]:
        """Relations used as tuplesets, per type. Checks always need all of their tuples."""
        found: dict[str, set[str]] = defaultdict(set)
        for (type_name, _), relation in self._relations.items():
            for node in walk(relation.rewrite):
                if isinstance(node, TupleToUsersetNode):
                    found[type_name].add(node.tupleset)
        return {t: frozenset(rs) for t, rs in found.items()}

    def is_userset_target(self, type_name: str, relation: str) -> bool:
        return (type_name, relation) in self._userset_targets

    def subject_problem(self, subject: SubjectRef) -> str | None:
        if not self.has_type(subject.type):
            return f"type '{subject.type}' is not defined in the model"
        if subject.relation is not None and not self.has_relation(subject.type, subject.relation):
            return f"relation '{subject.type}#{subject.relation}' is not defined in the model"
        return None

    def query_problem(self, object_type: str, relation: str) -> str | None:
        if not self.has_type(object_type):
            return f"type '{object_type}' is not defined in the model"
        if not self.has_relation(object_type, relation):
            return f"relation '{object_type}#{relation}' is not defined in the model"
        return None

    def tuple_problem(self, t: RelationTuple) -> str | None:
        """Why a tuple cannot be stored under this model, or None if it is valid."""
        problem = self.query_problem(t.object.type, t.relation) or self.subject_problem(t.subject)
        if problem:
            return problem
        if not self.is_assignable(t.object.type, t.relation, t.subject):
            allowed = ", ".join(str(r) for r in self.direct_restrictions(t.object.type, t.relation))
            if not allowed:
                return f"'{t.object.type}#{t.relation}' is not directly assignable"
            return (
                f"'{t.subject}' cannot be assigned to '{t.object.type}#{t.relation}', "
                f"which accepts [{allowed}]"
            )
        return None
