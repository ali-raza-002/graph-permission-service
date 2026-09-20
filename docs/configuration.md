# Configuration

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

## Test settings

| Variable | Default | Used by |
|---|---|---|
| `WARDEN_TEST_DATABASE_URL` | `postgresql+asyncpg://warden:warden@127.0.0.1:5506/warden_test` | backend integration tests (the schema is dropped and recreated) |
| `WORKSPACES_TEST_DATABASE_URL` | `postgresql+asyncpg://warden:warden@127.0.0.1:5506/warden_demo_test` | demo-app tests |
| `WARDEN_TEST_REDIS_URL` | `redis://127.0.0.1:6406/15` | the Redis cache test; skipped when unreachable |
| `WARDEN_PROPERTY_EXAMPLES` | `150` | Hypothesis examples per property test |
