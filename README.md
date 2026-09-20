<div align="center">

# Warden

**Zanzibar-style authorization you can read.** Write a model in a small DSL, store relationship tuples,<br>
ask `check`, `expand` and `list-objects`, and see the exact path behind every allow or deny.

[![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)](backend/pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)](backend/src/warden/api)
[![Pydantic v2](https://img.shields.io/badge/Pydantic-v2-E92063?logo=pydantic&logoColor=white)](backend/src/warden/dsl/ast.py)
[![PostgreSQL 16](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](backend/migrations)
[![Next.js 15](https://img.shields.io/badge/Next.js-15-000000?logo=nextdotjs&logoColor=white)](web)
[![TypeScript strict](https://img.shields.io/badge/TypeScript-strict-3178C6?logo=typescript&logoColor=white)](web/tsconfig.json)
[![mypy strict](https://img.shields.io/badge/mypy-strict-2A6DB2)](mypy.ini)
[![Tested with Hypothesis](https://img.shields.io/badge/tested%20with-Hypothesis-F1C40F)](backend/tests/property)
[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)](.github/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

<br>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/playground-allowed-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/screenshots/playground-allowed-light.png">
  <img alt="The Warden playground: user:dev is allowed can_view on document:rfc-012-rebac, with the decisive path drawn as a graph through the exclusion, union and tuple-to-userset steps" src="docs/screenshots/playground-allowed-light.png" width="100%">
</picture>

<sub><code>user:dev</code> can view <code>document:rfc-012-rebac</code>. Each node is a step the evaluator took. The green edges are the decisive path: past <code>but not blocked</code>, through the <code>viewer</code> union, and on to inheritance via <code>viewer from parent</code>.</sub>

</div>

---

## Contents

- [Why this exists](#why-this-exists)
- [Highlights](#highlights)
- [Screenshots](#screenshots)
- [Architecture](#architecture)
- [The modelling language](#the-modelling-language)
- [How a check is answered](#how-a-check-is-answered)
- [Engineering decisions and trade-offs](#engineering-decisions-and-trade-offs)
- [Tech stack](#tech-stack)
- [Quickstart](#quickstart)
- [Configuration](#configuration)
- [API overview](#api-overview)
- [Python SDK and the FastAPI guard](#python-sdk-and-the-fastapi-guard)
- [Testing and benchmarks](#testing-and-benchmarks)
- [Project structure](#project-structure)
- [Roadmap](#roadmap)
- [License](#license)

## Why this exists

Most products start with `if user.role == "admin"` and end with permission logic spread across
a dozen services, each with a slightly different idea of who can see what. Google's
[Zanzibar paper](https://research.google/pubs/zanzibar-googles-consistent-global-authorization-system/)
describes the alternative: model permissions as relationships, keep those relationships in one
place, and answer every "can X do Y to Z?" from a consistent snapshot. OpenFGA and SpiceDB brought
that design to the rest of the industry.

Warden is a compact, readable implementation of the same ideas. It covers the parts that make
Zanzibar hard: a typed modelling language, snapshot reads with consistency tokens (the
"new enemy" problem), recursive evaluation that survives cycles, and reverse lookups. It also
covers the part that is usually missing: **an explanation**. Every decision is logged with the
trace that produced it, and the console draws that trace as a graph.

It ships with **Workspaces**, a small document-sharing SaaS (orgs, teams, folders, documents)
that hands every permission decision to Warden through a typed Python SDK. You can switch users
and watch the answers change.

## Highlights

| | |
|---|---|
| **A real DSL** | A Lark grammar with direct types (`[user, team#member, user:*]`), computed usersets, `or` / `and` / `but not`, and tuple-to-userset (`viewer from parent`). It parses into frozen Pydantic v2 AST models. A semantic validator reports errors with line and column, and a printer formats the source in a stable way. |
| **Versioned models** | Each store keeps an append-only list of model versions. Writes and checks can pin a `model_id` and default to the latest. |
| **MVCC tuple store** | Every write transaction bumps the store revision and stamps tuples with `created_revision` and `deleted_revision`, so any retained revision can be read without holding a transaction open. Covering indexes serve forward (`object#relation`) and reverse (`subject`) lookups. |
| **Consistency tokens** | Writes return a `zk1.` token (a "zookie"). Reads accept `minimize_latency`, `at_least_as_fresh`, `at_exact_snapshot` or `fully_consistent`, which closes the new-enemy window. |
| **Concurrent recursive check** | Sub-problems run concurrently with `asyncio`. Unions stop at the first grant and intersections at the first denial. In-flight work is shared, a wait-for graph detects cycles, and cycles are resolved by Kleene iteration up to a least fixpoint. A depth limit and a deadline bound the work. |
| **Explain traces** | `check` returns a typed `TraceNode` tree with `direct`, `computed`, `tuple_to_userset`, `union`, `intersection`, `exclusion`, `tuple` and `cycle` steps, each with a result and timing. |
| **Expand, ListObjects, ListUsers** | `expand` returns the userset tree. ListObjects walks the graph backwards from the subject, then confirms each candidate with a check that shares one memo table. |
| **Contextual tuples** | Facts that hold for a single request (for example an IP-based group taken from the session). Results that use them stay out of the shared cache. |
| **Per-revision cache** | Cache keys include store, model and revision. Data at a revision never changes, so entries never need invalidation. The cache runs in memory, in Redis, or not at all. |
| **Decision log** | Every check and list query is written asynchronously with its trace, latency, revision and API key. The console has charts, filters and a trace viewer. |
| **Scoped API keys** | Keys are hashed and carry scopes (`check`, `tuples:write`, `models:write`, `keys:admin`, ...), and can be limited to a single store. |
| **Console** | Next.js 15, shadcn/ui, a Monaco DSL editor with live validation markers, a tuple browser with change history, and a playground that draws check and expand results with React Flow. |

## Screenshots

**Overview.** Decisions per hour, allow rate, p95 latency and the tuples in the store.

![Store overview with decision charts, allow rate, p95 latency and tuple counts](docs/screenshots/overview-light.png)

**Why denied.** In `can_view: viewer but not blocked` the subtracted side matched, so the viewer branch was skipped.

![Playground showing a denied check because the user is blocked](docs/screenshots/playground-denied-light.png)

**DSL editor.** Semantic errors appear inline at their line and column, for example a tuple-to-userset that points at a relation that does not exist.

![Monaco DSL editor with an inline error at line 41 column 32](docs/screenshots/model-validation-light.png)

**Expand.** The userset tree for `document:rfc-012-rebac#editor`.

![Expand view showing the userset tree for document editor](docs/screenshots/expand-light.png)

**Tuples.** Browse and filter the relationship tuples at a snapshot revision.

![Tuple browser at a snapshot revision](docs/screenshots/tuples-light.png)

**Change history.** Every write and delete, grouped by the revision that applied it.

![Tuple change history grouped by revision](docs/screenshots/tuple-history-light.png)

**Decision log.** Every check is stored with its revision, model, latency and full trace.

![Decision log entry with metadata and its trace graph](docs/screenshots/decision-detail-light.png)

**Blocked.** Dev can see the folder but not the document, and "See why" opens that trace in the console.

![Workspaces demo showing a blocked document](docs/screenshots/demo-blocked-light.png)

**Workspaces demo.** Folders come from ListObjects, "Who can see this" from ListUsers, and the footer shows the check that let you in.

![Workspaces demo app showing a document, the people who can see it, and the Warden decision](docs/screenshots/demo-document-light.png)

**Sharing.** Each change is a tuple write, and the next check is at least as fresh as that write.

![Share dialog in the Workspaces demo](docs/screenshots/demo-share-light.png)

## Architecture

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

### Read path

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

### Closing the new-enemy window

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

### User flow

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

### Data model

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

## The modelling language

This is the model that runs the Workspaces demo ([`authorization.warden`](demo-app/src/workspaces/authorization.warden)):

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

## How a check is answered

The checker in [`engine/check.py`](backend/src/warden/engine/check.py) treats each
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

## Engineering decisions and trade-offs

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

## Tech stack

| Layer | Choice |
|---|---|
| API | Python 3.12, FastAPI, Pydantic v2, pydantic-settings, structlog |
| Language | Lark (LALR grammar) into a typed Pydantic AST, plus a semantic validator and printer |
| Storage | PostgreSQL 16, SQLAlchemy 2.0 async, asyncpg, Alembic |
| Cache | in-process LRU or Redis 7 (optional) |
| SDK | httpx async client, Pydantic models, a FastAPI `require()` dependency |
| Demo app | FastAPI "Workspaces" with its own Postgres schema |
| Console | Next.js 15 App Router, React 19, TypeScript (strict), shadcn/ui, Tailwind CSS 4, TanStack Query, React Flow + dagre, Monaco editor, Recharts, zod |
| Quality | pytest, Hypothesis, mypy `--strict`, Ruff, ESLint, Vitest, GitHub Actions |
| Ops | Docker Compose, with every port bound to `127.0.0.1` |

## Quickstart

### Local (no Docker)

Requires Python 3.12 (or 3.13), Node 22+ with pnpm 9, PostgreSQL 16 or newer, and Redis.

```bash
make install    # venv (python3.12, else 3.13), editable packages, web deps, copies .env files
make services   # Postgres on 5506 and Redis on 6406, data kept in .data/
                # PG_BIN=/opt/homebrew/opt/postgresql@17/bin pins a specific Postgres
make migrate    # alembic upgrade head
make seed       # demo stores, tuples, the demo-app key, the console key and a day of decisions
make dev        # API, Workspaces demo and console together
```

| Service | URL |
|---|---|
| Console | http://localhost:3106 |
| Workspaces demo UI | http://localhost:3106/demo |
| Warden API + OpenAPI docs | http://127.0.0.1:8106/docs |
| Workspaces API | http://127.0.0.1:27106 |

Try `user:dev` → `can_view` → `document:rfc-012-rebac` (allowed through a nested team and folder
inheritance), then the same user on `document:credential-leak-review` (denied by
`but not blocked`).

`make services-down` stops Postgres and Redis. `make help` lists every task.

### Docker Compose

```bash
# compose refuses to start without these
cat >> .env <<EOF
WARDEN_BOOTSTRAP_ADMIN_KEY=$(openssl rand -base64 32)
WARDEN_CONSOLE_API_KEY=wdn_$(openssl rand -hex 4)_$(openssl rand -hex 24)
WORKSPACES_WARDEN_API_KEY=wdn_$(openssl rand -hex 4)_$(openssl rand -hex 24)
EOF

docker compose up --build
```

A one-shot `seed` service loads the demo data on first start. To rebuild it, run
`docker compose run --rm seed python scripts/seed.py --reset`.

## Configuration

All Warden settings use the `WARDEN_` prefix and are read from the environment or `.env`.

| Variable | Default | Purpose |
|---|---|---|
| `WARDEN_ENV` | `development` | `production` rejects placeholder or short bootstrap keys |
| `WARDEN_HOST` / `WARDEN_PORT` | `127.0.0.1` / `8106` | bind address |
| `WARDEN_DATABASE_URL` | `postgresql+asyncpg://warden:warden@127.0.0.1:5506/warden` | Postgres DSN |
| `WARDEN_DB_POOL_SIZE` / `WARDEN_DB_MAX_OVERFLOW` | `20` / `10` | connection pool |
| `WARDEN_MAX_CONCURRENT_READS` | `24` | process-wide cap on concurrent snapshot queries |
| `WARDEN_CACHE_BACKEND` | `memory` | `memory`, `redis` or `none` |
| `WARDEN_REDIS_URL` | `redis://127.0.0.1:6406/0` | used when the cache backend is `redis` |
| `WARDEN_CACHE_TTL_SECONDS` / `WARDEN_CACHE_MAX_ENTRIES` | `300` / `200000` | cache bounds |
| `WARDEN_REVISION_QUANTIZATION_MS` | `2000` | how long `minimize_latency` reuses a revision |
| `WARDEN_MAX_CHECK_DEPTH` | `25` | recursion limit (1 to 100) |
| `WARDEN_QUERY_DEADLINE_MS` | `10000` | per-query time budget |
| `WARDEN_MAX_TUPLES_PER_WRITE` | `500` | writes + deletes per transaction |
| `WARDEN_MAX_CONTEXTUAL_TUPLES` | `100` | per request |
| `WARDEN_MAX_BATCH_CHECKS` | `100` | items per batch-check |
| `WARDEN_LIST_MAX_RESULTS` / `WARDEN_LIST_MAX_CANDIDATES` | `1000` / `10000` | ListObjects and ListUsers bounds |
| `WARDEN_TUPLE_HISTORY_RETENTION_HOURS` | `24` | snapshot history kept for consistency tokens |
| `WARDEN_DECISION_RETENTION_DAYS` | `30` | decision log retention |
| `WARDEN_GC_ENABLED` / `WARDEN_GC_INTERVAL_SECONDS` | `true` / `600` | background garbage collection |
| `WARDEN_DECISION_LOG` | `async` | `async`, `sync` or `off` |
| `WARDEN_DECISION_TRACE_MAX_NODES` | `400` | traces are pruned to this size before storage |
| `WARDEN_BOOTSTRAP_ADMIN_KEY` | none | admin key accepted with every scope |
| `WARDEN_PRINCIPAL_CACHE_TTL_SECONDS` | `30` | how long other replicas may keep honouring a revoked key |
| `WARDEN_CORS_ORIGINS` | `["http://localhost:3106"]` | allowed browser origins |
| `WARDEN_LOG_LEVEL` / `WARDEN_LOG_JSON` | `INFO` / `false` | structured logging |

Workspaces demo (`WORKSPACES_` prefix): `PORT` (27106), `DATABASE_URL`, `WARDEN_URL`,
`WARDEN_API_KEY` (required), `WARDEN_STORE_ID` (`st_workspaces_demo`).

Console (`web/.env.local`): `WARDEN_API_URL`, `WARDEN_API_KEY` (the console key, never the
bootstrap key), `WORKSPACES_API_URL`, and optionally `CONSOLE_BASIC_AUTH=user:password`.

## API overview

Every request sends `Authorization: Bearer <api key>`. The full OpenAPI schema is served at `/docs`.

| Method | Path | Scope | Description |
|---|---|---|---|
| `POST` | `/v1/stores` | `stores:admin` | create a store |
| `GET` | `/v1/stores`, `/v1/stores/{id}` | `models:read` | list stores, get one |
| `GET` | `/v1/stores/{id}/overview` | `decisions:read` | dashboard stats |
| `DELETE` | `/v1/stores/{id}` | `stores:admin` | delete a store (data removed by GC) |
| `POST` | `/v1/dsl/validate` | `models:read` | parse + validate DSL, returns issues and formatted source |
| `POST` | `/v1/stores/{id}/models` | `models:write` | write a new model version |
| `GET` | `/v1/stores/{id}/models[/latest\|/{model_id}]` | `models:read` | model history |
| `POST` | `/v1/stores/{id}/tuples/write` | `tuples:write` | batch writes and deletes with preconditions, returns revision and token |
| `GET` | `/v1/stores/{id}/tuples` | `tuples:read` | filter tuples at a snapshot |
| `GET` | `/v1/stores/{id}/changes` | `tuples:read` | change feed by revision |
| `POST` | `/v1/stores/{id}/check` | `check` | check with optional `explain`, contextual tuples, consistency |
| `POST` | `/v1/stores/{id}/batch-check` | `check` | many checks against one snapshot |
| `POST` | `/v1/stores/{id}/expand` | `check` | userset tree |
| `POST` | `/v1/stores/{id}/list-objects` | `check` | objects a user holds a relation on |
| `POST` | `/v1/stores/{id}/list-users` | `check` | subjects holding a relation on an object |
| `GET` | `/v1/stores/{id}/decisions[/stats\|/{decision_id}]` | `decisions:read` | decision log, charts, single trace |
| `POST` `GET` `DELETE` | `/v1/api-keys` | `keys:admin` | create, list and revoke keys |
| `GET` | `/healthz`, `/readyz` | none | liveness, readiness (database) |

```bash
curl -s http://127.0.0.1:8106/v1/stores/st_workspaces_demo/check \
  -H "Authorization: Bearer $WARDEN_CONSOLE_API_KEY" -H "Content-Type: application/json" \
  -d '{
        "tuple_key": {"object": "document:rfc-012-rebac", "relation": "can_view", "user": "user:dev"},
        "consistency": {"mode": "minimize_latency"},
        "explain": true
      }'
```

```jsonc
{
  "allowed": true,
  "decision_id": "dec_...",
  "model_id": "md_...",
  "revision": 7,
  "consistency_token": "zk1....",
  "cached": false,
  "duration_ms": 7.2,
  "trace": { "kind": "check", "label": "document:rfc-012-rebac#can_view", "result": "allowed", "children": [ ... ] },
  "stats": { "dispatches": 18, "memo_hits": 0, "cache_hits": 0, "queries": 7 }
}
```

Errors share one envelope with a stable `code`: `not_found`, `validation_failed`,
`invalid_tuple`, `precondition_failed`, `invalid_consistency_token`, `snapshot_too_old`,
`resolution_too_complex`, `deadline_exceeded`, `unauthenticated`, `forbidden`, `conflict`.

## Python SDK and the FastAPI guard

```python
from warden_sdk import WardenClient

async with WardenClient("http://127.0.0.1:8106", api_key, store_id="st_workspaces_demo") as warden:
    await warden.write(
        writes=["document:plan#viewer@user:bob"],
        must_not_exist=["document:plan#blocked@user:bob"],  # precondition
    )
    # The client remembers the write's token and sends it as at_least_as_fresh.
    result = await warden.check("document:plan", "can_view", "user:bob")
    docs = await warden.list_objects("document", "can_view", "user:bob")
```

The Workspaces app protects its routes with a single dependency:

```python
guard = WardenGuard(client=get_warden, subject=current_subject)
can_edit_document = guard.require("can_edit", "document", "document_id")


@router.patch("/documents/{document_id}")
async def update_document(
    document_id: str,
    body: DocumentUpdate,
    decision: Annotated[CheckResult, Depends(can_edit_document)],
) -> DocumentDetail: ...
```

A denial becomes `403` with the `decision_id` attached, so support can open the exact trace. If
Warden is unreachable the guard returns `503 authorization_unavailable`. It fails closed, never
open. Reads are retried on connection errors and 502/503/504. Writes are retried only when
repeating them is harmless.

## Testing and benchmarks

```bash
make lint        # ruff check + ruff format --check + eslint
make typecheck   # mypy --strict over backend, sdk, demo-app, scripts + tsc --noEmit
make test        # pytest (backend, sdk, demo-app) + vitest; integration tests need Postgres on 5506
make bench       # check / list-objects latency on a synthetic organisation
```

- **Unit tests** cover the grammar, validator diagnostics, the printer, the evaluator (unions, intersections, exclusions, wildcards, cycles, depth limits) and core primitives.
- **Property tests** ([Hypothesis](backend/tests/property/test_engine_properties.py)) generate random models and tuple sets. They assert that `check`, `expand` and `list_objects` all agree with an independent least-fixpoint oracle, and that formatting is a fixed point. `WARDEN_PROPERTY_EXAMPLES` controls the depth (150 by default).
- **Integration tests** run against real Postgres and cover the HTTP API, snapshot reads, preconditions, consistency tokens and the new-enemy window, GC behind the retention horizon, API-key scopes and revocation lag, the Redis cache, and parity between the in-memory and Postgres tuple readers.
- **SDK and demo-app tests** cover retries, read-your-writes tokens, the `require()` guard and the Workspaces flows.
- CI runs all of the above, plus `next build` and `docker compose build`.

Sample `make bench` run on an Apple M4 Pro laptop with local Postgres 17. It uses 25,001
tuples (2,000 users, 200 nested groups, a 500-folder tree, 10,000 documents), concurrency 32,
the in-memory cache, and runs in-process:

| scenario | requests | p50 ms | p95 ms | p99 ms | req/s |
|---|---:|---:|---:|---:|---:|
| check, cold cache | 2000 | 156.16 | 300.46 | 341.52 | 220 |
| check, warm cache | 2000 | 0.02 | 0.02 | 0.02 | 41,181 |
| list-objects | 20 | 94.58 | 2369.08 | 2476.48 | 8 |

Cold checks are bound by Postgres round trips through deep folder chains. With
`--concurrency 4`, the cold-cache p50 drops to about 21 ms. These numbers come from one
machine and are meant for comparing changes, not for marketing.

## Project structure

```text
warden-authz/
├── backend/                     Warden service (package `warden`)
│   ├── src/warden/
│   │   ├── dsl/                 grammar.lark, parser, Pydantic AST, typesystem, validator, printer
│   │   ├── model/               store + model versioning
│   │   ├── tuples/              MVCC repository, revision resolver, write service
│   │   ├── engine/              check.py, expand.py, listing.py, reader.py, trace.py
│   │   ├── queries/             read path: snapshot -> cache -> evaluate -> trace -> log
│   │   ├── cache/               memory / Redis / null backends
│   │   ├── decisions/           async decision log, stats, retention
│   │   ├── auth/                hashed, scoped API keys and principal cache
│   │   ├── api/                 FastAPI app, routes, error envelope
│   │   ├── core/                refs, consistency tokens, ids, pagination, errors
│   │   ├── db/                  SQLAlchemy tables and engine
│   │   └── maintenance.py       history and decision garbage collection
│   ├── migrations/              Alembic
│   ├── scripts/bench.py
│   └── tests/                   unit/, property/, integration/
├── sdk/                         warden-sdk: typed async client + FastAPI WardenGuard
├── demo-app/                    Workspaces: orgs, teams, folders, documents (FastAPI)
│   └── src/workspaces/authorization.warden
├── web/                         Next.js console + /demo UI
│   └── src/
│       ├── app/(console)/       stores, overview, model, tuples, playground, decisions
│       ├── app/api/             server-side proxies to Warden and Workspaces
│       ├── components/          console/, demo/, graph/ (React Flow), ui/ (shadcn)
│       └── lib/                 typed API client + zod schemas, graph layout, request guard
├── scripts/                     seed.py, services.sh (local Postgres + Redis)
├── docker/                      Python Dockerfile
├── docker-compose.yml
└── Makefile
```

## Roadmap

- [ ] Watch API (server-sent events over the `/changes` feed) for cache warming and audit streams
- [ ] Conditions (CEL-style caveats on tuples evaluated with request context)
- [ ] Read replicas: route snapshot reads to replicas that have reached the requested revision
- [ ] Model migration assistant: diff two model versions and list the checks whose answers change
- [ ] TypeScript SDK sharing the console's zod schemas
- [ ] OpenTelemetry spans per sub-problem, linked from the decision log

## License

[MIT](LICENSE)
