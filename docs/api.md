# HTTP API

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

## Examples

Captured from the Docker Compose stack after `seed` (ids and timings vary). `$K` holds the console
key and `$U` is `http://127.0.0.1:8106/v1/stores/st_workspaces_demo`.

**Write a tuple.** The response carries the new revision and a consistency token.

```bash
curl -s $U/tuples/write -H "Authorization: Bearer $K" -H "Content-Type: application/json" \
  -d '{"writes": [{"object": "document:press-kit", "relation": "viewer", "user": "user:fatima"}]}'
```

```json
{"revision":8,"consistency_token":"zk1.c3Rfd29ya3NwYWNlc19kZW1vOjg","model_id":"md_01m6y7dkwhzq4sag49e8n7te1v","written":1,"deleted":0}
```

**Check at least as fresh as that write**, so the new share is guaranteed to be visible:

```bash
curl -s $U/check -H "Authorization: Bearer $K" -H "Content-Type: application/json" \
  -d '{"tuple_key": {"object": "document:press-kit", "relation": "can_view", "user": "user:fatima"},
       "consistency": {"mode": "at_least_as_fresh", "token": "zk1.c3Rfd29ya3NwYWNlc19kZW1vOjg"}}'
```

```jsonc
{"model_id": "md_01m6y7dkwhzq4sag49e8n7te1v", "revision": 8, "consistency_token": "zk1.c3Rfd29ya3NwYWNlc19kZW1vOjg",
 "duration_ms": 4.984, "allowed": true, "decision_id": "dec_01m6y7ebhs77wkqw81e4hptfjd", "cached": false,
 "trace": { ... },
 "stats": {"dispatches": 8, "memo_hits": 0, "cache_hits": 0, "queries": 2}}
```

**A denial** (`user:dev` is on the document's `blocked` relation):

```jsonc
// POST $U/check {"tuple_key": {"object": "document:credential-leak-review", "relation": "can_view", "user": "user:dev"}}
{"model_id": "md_01m6y7dkwhzq4sag49e8n7te1v", "revision": 7, "consistency_token": "zk1.c3Rfd29ya3NwYWNlc19kZW1vOjc",
 "duration_ms": 0.483, "allowed": false, "decision_id": "dec_01m6y7e3m8j9n1sy4zp2mg1ms5", "cached": true,
 "trace": { ... }, "stats": {"dispatches": 0, "memo_hits": 0, "cache_hits": 1, "queries": 0}}
```

**List objects:**

```jsonc
// POST $U/list-objects {"object_type": "folder", "relation": "viewer", "user": "user:fatima"}
{"model_id":"md_01m6y7dkwhzq4sag49e8n7te1v","revision":8,"consistency_token":"zk1.c3Rfd29ya3NwYWNlc19kZW1vOjg",
 "duration_ms":16.73,"objects":["folder:partners"],"truncated":false,"decision_id":"dec_01m6y7e3pcb097002mfv6p11vy"}
```

**Errors.** An unknown relation returns 422, a missing key 401:

```jsonc
// POST $U/check {"tuple_key": {"object": "document:press-kit", "relation": "can_fly", "user": "user:dev"}}
{"error":{"code":"invalid_tuple","message":"relation 'document#can_fly' is not defined in the model",
 "details":[{"tuple":"document:press-kit#can_fly@user:dev","reason":"relation 'document#can_fly' is not defined in the model"}]}}

// POST $U/check without an Authorization header -> HTTP 401
{"error":{"code":"unauthenticated","message":"missing bearer API key","details":[]}}
```

Errors share one envelope with a stable `code`: `not_found`, `validation_failed`,
`invalid_tuple`, `precondition_failed`, `invalid_consistency_token`, `snapshot_too_old`,
`resolution_too_complex`, `deadline_exceeded`, `unauthenticated`, `forbidden`, `conflict`.
