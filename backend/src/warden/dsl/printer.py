from __future__ import annotations

from warden.dsl.ast import (
    AuthorizationModel,
    ComputedNode,
    DirectNode,
    ExclusionNode,
    IntersectionNode,
    Rewrite,
    TupleToUsersetNode,
    UnionNode,
)

_UNION, _INTERSECTION, _EXCLUSION, _PRIMARY = 1, 2, 3, 4


def _precedence(node: Rewrite) -> int:
    match node:
        case UnionNode():
            return _UNION
        case IntersectionNode():
            return _INTERSECTION
        case ExclusionNode():
            return _EXCLUSION
        case _:
            return _PRIMARY


def _wrap(node: Rewrite, minimum: int) -> str:
    text = format_rewrite(node)
    return f"({text})" if _precedence(node) < minimum else text


def format_rewrite(node: Rewrite) -> str:
    match node:
        case DirectNode(types=types):
            return "[" + ", ".join(str(t) for t in types) + "]"
        case ComputedNode(relation=relation):
            return relation
        case TupleToUsersetNode(tupleset=tupleset, computed=computed):
            return f"{computed} from {tupleset}"
        case UnionNode(children=children):
            # Both operators are associative and the parser flattens them, so nested
            # nodes of the same kind print without parentheses.
            return " or ".join(
                format_rewrite(c) if isinstance(c, UnionNode) else _wrap(c, _INTERSECTION)
                for c in children
            )
        case IntersectionNode(children=children):
            return " and ".join(
                format_rewrite(c) if isinstance(c, IntersectionNode) else _wrap(c, _EXCLUSION)
                for c in children
            )
        case ExclusionNode(base=base, subtract=subtract):
            # Exclusion is left-associative, so a nested base needs no parentheses.
            left = (
                format_rewrite(base) if isinstance(base, ExclusionNode) else _wrap(base, _PRIMARY)
            )
            return f"{left} but not {_wrap(subtract, _PRIMARY)}"


def format_model(model: AuthorizationModel) -> str:
    lines = ["model", f"  schema {model.schema_version}"]
    for type_def in model.types:
        lines.extend(["", f"type {type_def.name}"])
        if type_def.relations:
            lines.append("  relations")
            lines.extend(
                f"    define {r.name}: {format_rewrite(r.rewrite)}" for r in type_def.relations
            )
    return "\n".join(lines) + "\n"
