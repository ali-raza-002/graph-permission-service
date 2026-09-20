# The modelling language

This is the model that runs the Workspaces demo ([`authorization.warden`](../demo-app/src/workspaces/authorization.warden)):

```text
model
  schema 1.1

type user

type org
  relations
    define admin: [user]
    define member: [user] or admin

type team
  relations
    define org: [org]
    define lead: [user]
    define member: [user, team#member] or lead

type folder
  relations
    define org: [org]
    define parent: [folder]
    define owner: [user]
    define editor: [user, team#member] or owner or editor from parent or admin from org
    define viewer: [user, user:*, team#member, org#member] or editor or viewer from parent

type document
  relations
    define org: [org]
    define parent: [folder]
    define owner: [user]
    define blocked: [user]
    define editor: [user, team#member] or owner or editor from parent
    define viewer: [user, user:*, team#member, org#member] or editor or viewer from parent
    define can_view: viewer but not blocked
    define can_edit: editor but not blocked
    // External collaborators may edit, but only org members can reshare.
    define can_share: owner or (can_edit and member from org)
    define can_delete: owner or admin from org
    define can_manage_access: owner or admin from org
```

| Construct | Meaning | AST node |
|---|---|---|
| `[user, team#member, user:*]` | subjects that may be written directly: a type, a userset, or a public wildcard | `DirectNode` |
| `owner` | everyone who has another relation on the same object | `ComputedNode` |
| `viewer from parent` | follow the `parent` tuples, then take `viewer` on each target | `TupleToUsersetNode` |
| `a or b`, `a and b`, `a but not b` | union, intersection, exclusion. Precedence from tightest: `but not`, `and`, `or` | `UnionNode`, `IntersectionNode`, `ExclusionNode` |

The validator rejects unknown types and relations, duplicates, tuple-to-userset through relations
that cannot hold objects, `from` targets that no reachable type defines, and relations that no
tuple can ever satisfy. Each issue carries a code, a message and a `line:column`. Unused types
produce warnings.
