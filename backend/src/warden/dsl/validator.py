from __future__ import annotations

from warden.dsl.ast import (
    AuthorizationModel,
    ComputedNode,
    DirectNode,
    ExclusionNode,
    IntersectionNode,
    Rewrite,
    TupleToUsersetNode,
    TypeDef,
    UnionNode,
)
from warden.dsl.issues import DslIssue, ModelCompileError
from warden.dsl.parser import parse_model
from warden.dsl.typesystem import TypeSystem, walk

SUPPORTED_SCHEMAS = frozenset({"1.1"})


class _Validator:
    def __init__(self, model: AuthorizationModel) -> None:
        self.model = model
        self.ts = TypeSystem(model)
        self.issues: list[DslIssue] = []

    def run(self) -> list[DslIssue]:
        if self.model.schema_version not in SUPPORTED_SCHEMAS:
            self.issues.append(
                DslIssue.at(
                    "unsupported_schema",
                    f"schema {self.model.schema_version} is not supported, use 1.1",
                    None,
                )
            )
        self._check_duplicates()
        for type_def in self.model.types:
            for relation in type_def.relations:
                for node in walk(relation.rewrite):
                    self._check_node(type_def, node)
        if not any(i.severity == "error" for i in self.issues):
            self._check_entrypoints()
            self._check_unused_types()
        return sorted(self.issues, key=lambda i: (i.line, i.column))

    def _check_duplicates(self) -> None:
        seen_types: set[str] = set()
        for type_def in self.model.types:
            if type_def.name in seen_types:
                self.issues.append(
                    DslIssue.at(
                        "duplicate_type",
                        f"type '{type_def.name}' is defined more than once",
                        type_def.pos,
                        len(type_def.name),
                    )
                )
            seen_types.add(type_def.name)
            seen_relations: set[str] = set()
            for relation in type_def.relations:
                if relation.name in seen_relations:
                    self.issues.append(
                        DslIssue.at(
                            "duplicate_relation",
                            f"relation '{relation.name}' is defined more than once on "
                            f"type '{type_def.name}'",
                            relation.pos,
                            len(relation.name),
                        )
                    )
                seen_relations.add(relation.name)

    def _check_node(self, type_def: TypeDef, node: Rewrite) -> None:
        match node:
            case DirectNode(types=restrictions):
                for restriction in restrictions:
                    if not self.ts.has_type(restriction.type):
                        self.issues.append(
                            DslIssue.at(
                                "unknown_type",
                                f"type '{restriction.type}' is not defined",
                                restriction.pos,
                                len(restriction.type),
                            )
                        )
                    elif restriction.relation and not self.ts.has_relation(
                        restriction.type, restriction.relation
                    ):
                        self.issues.append(
                            DslIssue.at(
                                "unknown_relation",
                                f"relation '{restriction.relation}' is not defined on "
                                f"type '{restriction.type}'",
                                restriction.pos,
                                len(str(restriction)),
                            )
                        )
            case ComputedNode(relation=relation):
                if not self.ts.has_relation(type_def.name, relation):
                    self.issues.append(
                        DslIssue.at(
                            "unknown_relation",
                            f"relation '{relation}' is not defined on type '{type_def.name}'",
                            node.pos,
                            len(relation),
                        )
                    )
            case TupleToUsersetNode(tupleset=tupleset, computed=computed):
                self._check_tuple_to_userset(type_def, node, tupleset, computed)
            case _:
                pass

    def _check_tuple_to_userset(
        self, type_def: TypeDef, node: TupleToUsersetNode, tupleset: str, computed: str
    ) -> None:
        span = len(f"{computed} from {tupleset}")
        if not self.ts.has_relation(type_def.name, tupleset):
            self.issues.append(
                DslIssue.at(
                    "unknown_relation",
                    f"tupleset relation '{tupleset}' is not defined on type '{type_def.name}'",
                    node.pos,
                    span,
                )
            )
            return
        tupleset_rewrite = self.ts.relation(type_def.name, tupleset).rewrite
        direct_only = isinstance(tupleset_rewrite, DirectNode) and all(
            r.relation is None and not r.wildcard for r in tupleset_rewrite.types
        )
        if not direct_only:
            self.issues.append(
                DslIssue.at(
                    "invalid_tupleset",
                    f"'{tupleset}' is used as a tupleset, so it must be a direct relation to "
                    "plain types such as [folder]",
                    node.pos,
                    span,
                )
            )
            return
        parents = self.ts.tupleset_parent_types(type_def.name, tupleset)
        if parents and not any(self.ts.has_relation(p, computed) for p in parents):
            self.issues.append(
                DslIssue.at(
                    "unknown_relation",
                    f"none of the types reachable through '{tupleset}' "
                    f"({', '.join(parents)}) define relation '{computed}'",
                    node.pos,
                    span,
                )
            )

    def _check_unused_types(self) -> None:
        """A type with no relations that no relation accepts can never appear in a tuple."""
        referenced = {
            restriction.type
            for type_def in self.model.types
            for relation in type_def.relations
            for node in walk(relation.rewrite)
            if isinstance(node, DirectNode)
            for restriction in node.types
        }
        for type_def in self.model.types:
            if not type_def.relations and type_def.name not in referenced:
                self.issues.append(
                    DslIssue.at(
                        "unused_type",
                        f"type '{type_def.name}' has no relations and no relation accepts it, "
                        "so it can never appear in a tuple",
                        type_def.pos,
                        len(type_def.name),
                        severity="warning",
                    )
                )

    def _check_entrypoints(self) -> None:
        """Least-fixpoint over the model: a relation is satisfiable only if some chain of
        rewrites bottoms out in a directly assignable relation."""
        reachable: set[tuple[str, str]] = set()

        def satisfiable(type_name: str, node: Rewrite) -> bool:
            match node:
                case DirectNode():
                    return True
                case ComputedNode(relation=relation):
                    return (type_name, relation) in reachable
                case TupleToUsersetNode(tupleset=tupleset, computed=computed):
                    return any(
                        (parent, computed) in reachable
                        for parent in self.ts.tupleset_parent_types(type_name, tupleset)
                    )
                case UnionNode(children=children):
                    return any(satisfiable(type_name, c) for c in children)
                case IntersectionNode(children=children):
                    return all(satisfiable(type_name, c) for c in children)
                case ExclusionNode(base=base):
                    return satisfiable(type_name, base)

        changed = True
        while changed:
            changed = False
            for type_def in self.model.types:
                for relation in type_def.relations:
                    key = (type_def.name, relation.name)
                    if key not in reachable and satisfiable(type_def.name, relation.rewrite):
                        reachable.add(key)
                        changed = True

        for type_def in self.model.types:
            for relation in type_def.relations:
                if (type_def.name, relation.name) not in reachable:
                    self.issues.append(
                        DslIssue.at(
                            "no_entrypoint",
                            f"'{type_def.name}#{relation.name}' can never be granted: every path "
                            "loops back without reaching a directly assignable relation",
                            relation.pos,
                            len(relation.name),
                        )
                    )


def validate_model(model: AuthorizationModel) -> list[DslIssue]:
    return _Validator(model).run()


def compile_model(source: str) -> AuthorizationModel:
    """Parse and semantically validate DSL source, raising ModelCompileError on failure."""
    model = parse_model(source)
    errors = [issue for issue in validate_model(model) if issue.severity == "error"]
    if errors:
        raise ModelCompileError(errors)
    return model
