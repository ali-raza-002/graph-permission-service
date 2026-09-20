# Architecture

How Warden is put together and how a request flows through it. The
[README](../README.md) has the short version.

## Components

```mermaid
flowchart LR
    subgraph clients["Clients"]
        console["Console<br/>Next.js 15 + shadcn/ui"]
        demoui["Workspaces UI<br/>/demo"]
        sdkuser["Any service<br/>warden-sdk"]
    end

    subgraph web["web/ (Next.js server)"]
        proxy["Route-handler proxy<br/>/api/warden, /api/workspaces<br/>holds the console key, same-origin only"]
    end

    subgraph demo["demo-app/ Workspaces (FastAPI)"]
        routes["Routes guarded by<br/>guard.require('can_edit', 'document', ...)"]
        sdk["WardenClient<br/>typed, async, read-your-writes"]
    end

    subgraph warden["backend/ Warden API (FastAPI)"]
        api["api<br/>stores, models, tuples, check,<br/>expand, list-*, keys, decisions"]
        auth["auth<br/>hashed, scoped API keys"]
        dsl["dsl<br/>Lark grammar, AST, validator"]
        model["model<br/>versioned per store"]
        queries["queries<br/>read path orchestration"]
        engine["engine<br/>check, expand, list-objects, list-users"]
        tuples["tuples<br/>MVCC repository, revisions"]
        cache["cache<br/>memory / Redis"]
        decisions["decisions<br/>async batched log"]
        gc["maintenance<br/>history and decision GC"]
    end

    pg[("PostgreSQL 16<br/>tuples, revisions, models,<br/>keys, decisions")]
    wspg[("PostgreSQL<br/>workspaces schema")]
    redis[("Redis<br/>optional check cache")]

    console --> proxy
    demoui --> proxy
    proxy --> api
    proxy --> routes
    routes --> sdk
    sdkuser --> api
    sdk --> api
    routes --> wspg
    api --> auth
    api --> model
    api --> tuples
    api --> queries
    model --> dsl
    queries --> engine
    queries --> cache
    queries --> decisions
    engine --> tuples
    tuples --> pg
    model --> pg
    decisions --> pg
    auth --> pg
    gc --> pg
    cache -.-> redis
```

## Read path

`check(request, consistency)` resolves a snapshot revision, then goes through the cache, evaluation and trace, and finally the decision log:

```mermaid
sequenceDiagram
    autonumber
    participant C as Client (SDK)
    participant A as API /check
    participant Q as QueryService
    participant R as RevisionResolver
    participant M as ModelService
    participant E as Checker
    participant K as Check cache
    participant P as Postgres
    participant D as DecisionLog

    C->>A: POST /v1/stores/{id}/check<br/>tuple_key, consistency, contextual_tuples
    A->>A: authenticate key, require scope "check"
    A->>Q: check(store, request, principal)
    Q->>M: resolve(model_id or latest)
    M-->>Q: compiled TypeSystem
    Q->>R: resolve(consistency)
    alt at_least_as_fresh and recent revision covers token
        R-->>Q: cached revision (no DB round trip)
    else otherwise
        R->>P: SELECT revision FROM stores
        R-->>Q: revision N
    end
    Q->>E: check(object, relation, subject) at revision N
    loop each distinct sub-problem (object, relation, subject)
        E->>K: get(store:model:N:key)
        alt hit
            K-->>E: allowed / denied
        else miss
            E->>P: tuples visible at N (forward or reverse index)
            P-->>E: rows
            E->>E: evaluate rewrite concurrently<br/>(union short-circuits, cycles tracked)
            E->>K: set(key, result)
        end
    end
    E-->>Q: Outcome(allowed, TraceNode)
    Q-)D: enqueue decision with trace (async batch insert)
    Q-->>A: CheckResponse
    A-->>C: allowed, trace, revision, consistency_token, stats
```

## Closing the new-enemy window

The classic Zanzibar failure: Alice removes Bob from a document, then adds a secret to it. A
stale read could still let Bob see the new content. Warden avoids this by returning a token
from every write and accepting it on later reads.

```mermaid
sequenceDiagram
    autonumber
    actor Owner as Anne (owner)
    participant WS as Workspaces API
    participant W as Warden
    actor Bob as Bob

    Owner->>WS: POST /documents/plan/unshare (Bob)
    WS->>W: tuples/write deletes=[document:plan#viewer@user:bob]
    W->>W: revision 41 to 42, stamp deleted_revision=42
    W-->>WS: revision 42, consistency_token zk1...
    Note over WS: SDK remembers the token (read_your_writes)
    Owner->>WS: PATCH /documents/plan (add secret)
    Bob->>WS: GET /documents/plan
    WS->>W: check can_view, at_least_as_fresh = zk1 (rev 42)
    W->>W: snapshot revision is at least 42, the delete is visible
    W-->>WS: allowed = false, decision_id
    WS-->>Bob: 403 forbidden (with decision id)
```

## User flow

```mermaid
flowchart TD
    start([Open the console]) --> store{Store exists?}
    store -- no --> create[Create a store]
    store -- yes --> overview[Overview<br/>decisions, allow rate, p95, tuples]
    create --> editor
    overview --> editor[Model editor<br/>Monaco + live validation]
    editor --> valid{Valid?}
    valid -- "errors at line:col" --> editor
    valid -- yes --> save[Save as new version<br/>v1, v2, ...]
    save --> tuples[Write tuples<br/>tuple browser or SDK]
    tuples --> playground[Playground]
    playground --> q{Query type}
    q --> check[Check<br/>+ contextual tuples<br/>+ consistency mode]
    q --> expand[Expand]
    q --> lo[List objects / List users]
    check --> tgraph[React Flow graph<br/>decisive path or full trace]
    expand --> tgraph
    tgraph --> log[Decision log<br/>filter, open the trace]
    log --> editor

    demo([Workspaces demo]) --> switch[Switch user]
    switch --> folders[Folders from ListObjects]
    folders --> doc[Open document<br/>guard.require can_view]
    doc -- denied --> why[See why: opens the trace in the playground]
    doc -- allowed --> share[Share / block<br/>tuple write returns a token]
    share --> doc
    why --> tgraph
```

## Data model

```mermaid
erDiagram
    stores ||--o{ store_revisions : "commits"
    stores ||--o{ authorization_models : "versions"
    stores ||--o{ relation_tuples : "holds"
    stores ||--o{ api_keys : "may scope"
    stores ||--o{ decisions : "logs"

    stores {
        string id PK
        string name
        bigint revision "incremented by every write tx"
        bigint gc_revision "oldest readable revision"
        timestamptz deleted_at
    }
    store_revisions {
        string store_id PK
        bigint revision PK
        timestamptz committed_at "maps retention time to a revision horizon"
    }
    authorization_models {
        string id PK
        string store_id FK
        int version "unique per store"
        string schema_version
        text dsl
        jsonb ast "Pydantic AST dump"
    }
    relation_tuples {
        bigint id PK
        string store_id FK
        string object_type
        string object_id
        string relation
        string subject_type
        string subject_id
        string subject_relation "empty string when not a userset"
        bigint created_revision
        bigint deleted_revision "null while live"
    }
    api_keys {
        string id PK
        string store_id FK "null means all stores"
        string prefix UK
        string key_hash
        string_array scopes
        timestamptz revoked_at
    }
    decisions {
        string id PK
        string store_id FK
        string model_id
        bigint revision
        string kind "check, list_objects, list_users"
        string object
        string relation
        string subject
        bool allowed
        float duration_ms
        bool cached
        jsonb trace
    }
```

Indexes on `relation_tuples`:

| Index | Columns | Purpose |
|---|---|---|
| `uq_relation_tuples_live` | full key, `WHERE deleted_revision IS NULL` | at most one live copy of a tuple |
| `ix_relation_tuples_forward` | `store, object_type, object_id, relation` INCLUDE subject + revisions | "who has `relation` on `object`" (index-only scans) |
| `ix_relation_tuples_reverse` | `store, subject_type, subject_id, subject_relation, object_type, relation` INCLUDE object_id + revisions | ListObjects reverse walk |
| `ix_relation_tuples_created` / `_deleted` | `store, created_revision` / `store, deleted_revision` | change feed and garbage collection |

## How a check is answered

The checker in [`engine/check.py`](../backend/src/warden/engine/check.py) treats each
`(object, relation, subject)` triple as a sub-problem:

1. **Memoize and share.** A sub-problem is resolved at most once per pass. If two branches need
   it, the second one waits on the first one's task, so graphs with diamonds cost time linear in
   the number of sub-problems rather than the number of paths.
2. **Run concurrently and short-circuit.** Children of a union or intersection run as `asyncio`
   tasks. A union returns on the first grant and an intersection on the first denial. Sibling
   work that nothing else waits on is cancelled.
3. **Detect cycles without deadlocks.** Waiting on shared in-flight work can deadlock when the
   relationships form a cycle (`team:a#member` contains `team:b#member`, which contains `team:a#member`). The evaluator
   keeps a wait-for graph. A request that would close a cycle is answered from an assumption
   (initially "denied") and the edge is marked.
4. **Iterate to a fixpoint.** If an assumption turns out wrong, the pass is repeated with the
   corrected assumptions. This is Kleene iteration from the bottom element. For monotone rewrites
   it converges to the least fixpoint, the answer a naive bottom-up evaluation would give. A cycle
   through the subtracted side of an exclusion, which is not monotone, fails with a clear error
   instead of looping.
5. **Bound the work.** `WARDEN_MAX_CHECK_DEPTH` limits recursion and `WARDEN_QUERY_DEADLINE_MS`
   limits wall-clock time. Both return typed errors.

The property tests compare `check`, `expand` and `list_objects` on random models and tuple sets
with an independent least-fixpoint oracle, so the cycle handling is tested, not just argued.

## Design decisions and trade-offs

| Decision | Why | Cost |
|---|---|---|
| **Revision counter per store**, tuples stamped with created/deleted revisions | Snapshot reads become a plain `WHERE created_revision <= N AND (deleted_revision IS NULL OR deleted_revision > N)`. There are no long transactions, and any retained revision can be read and cached. | Each write transaction takes a row lock on its store, so writes to one store are serialized. That is fine for authorization workloads, where reads dominate. |
| **Revision quantization** (`minimize_latency` reuses a revision for up to 2 s) | Concurrent checks land on the same revision and share cache entries, as in Zanzibar's quantized snapshots. | Results can be up to that long out of date unless the caller sends a token. The SDK sends its last write token automatically. |
| **Cache keyed by `store:model:revision`** | Data at a revision never changes, so there is nothing to invalidate. TTL and LRU only bound memory. | A new revision starts with a cold cache. Quantization keeps revisions from changing on every request. |
| **History retention plus GC** | Deleted tuples remain readable for `WARDEN_TUPLE_HISTORY_RETENTION_HOURS`. GC turns that window into a revision horizon and drops older history. | Tokens older than the horizon fail with `snapshot_too_old` instead of returning a silently wrong answer. |
| **ListObjects = reverse walk + confirm** | The reverse walk over the `subject` index produces a candidate superset cheaply. Intersections and exclusions are then decided by real checks that share one memo table. | Very broad relations (for example `user:*` on many objects) can hit `WARDEN_LIST_MAX_CANDIDATES`. The response then says `truncated: true`. |
| **Contextual tuples bypass the shared cache** | They change the answer without changing the revision. | Checks that use contextual tuples always evaluate. |
| **Async, batched decision log** | Logging stays off the hot path. Traces are pruned to `WARDEN_DECISION_TRACE_MAX_NODES`. | A crash can lose the last unflushed batch (at most about 500 ms). Set `WARDEN_DECISION_LOG=sync` if every decision must be durable. |
| **Frozen Pydantic AST, positions excluded from equality** | A compiled model can be shared safely across concurrent checks. Formatting is a fixed point (property-tested). | Slightly more ceremony than plain dataclasses. |
| **Console proxies the API with its own key** | The browser never holds a Warden key. The console key has every scope except `keys:admin`, and the proxy rejects cross-site and non-JSON requests. | Set `CONSOLE_BASIC_AUTH` whenever the console is reachable from anywhere but localhost. |
