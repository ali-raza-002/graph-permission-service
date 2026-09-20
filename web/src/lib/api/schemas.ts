import { z } from "zod";

export const pageOf = <T extends z.ZodType>(item: T) =>
  z.object({ items: z.array(item), next_cursor: z.string().nullable() });

export const storeSchema = z.object({
  id: z.string(),
  name: z.string(),
  revision: z.number().int(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Store = z.infer<typeof storeSchema>;

const typeRestrictionSchema = z.object({
  type: z.string(),
  relation: z.string().nullable(),
  wildcard: z.boolean(),
});
export type TypeRestriction = z.infer<typeof typeRestrictionSchema>;

export type Rewrite =
  | { kind: "direct"; types: TypeRestriction[] }
  | { kind: "computed"; relation: string }
  | { kind: "tuple_to_userset"; tupleset: string; computed: string }
  | { kind: "union"; children: Rewrite[] }
  | { kind: "intersection"; children: Rewrite[] }
  | { kind: "exclusion"; base: Rewrite; subtract: Rewrite };

export const rewriteSchema: z.ZodType<Rewrite> = z.lazy(() =>
  z.discriminatedUnion("kind", [
    z.object({ kind: z.literal("direct"), types: z.array(typeRestrictionSchema) }),
    z.object({ kind: z.literal("computed"), relation: z.string() }),
    z.object({
      kind: z.literal("tuple_to_userset"),
      tupleset: z.string(),
      computed: z.string(),
    }),
    z.object({ kind: z.literal("union"), children: z.array(rewriteSchema) }),
    z.object({ kind: z.literal("intersection"), children: z.array(rewriteSchema) }),
    z.object({ kind: z.literal("exclusion"), base: rewriteSchema, subtract: rewriteSchema }),
  ]),
);

export const authorizationModelSchema = z.object({
  schema_version: z.string(),
  types: z.array(
    z.object({
      name: z.string(),
      relations: z.array(z.object({ name: z.string(), rewrite: rewriteSchema })),
    }),
  ),
});
export type AuthorizationModel = z.infer<typeof authorizationModelSchema>;

export const modelSummarySchema = z.object({
  id: z.string(),
  store_id: z.string(),
  version: z.number().int(),
  schema_version: z.string(),
  created_at: z.string(),
});
export type ModelSummary = z.infer<typeof modelSummarySchema>;

export const modelDetailSchema = modelSummarySchema.extend({
  dsl: z.string(),
  ast: authorizationModelSchema,
});
export type ModelDetail = z.infer<typeof modelDetailSchema>;

export const dslIssueSchema = z.object({
  code: z.string(),
  message: z.string(),
  line: z.number().int(),
  column: z.number().int(),
  end_line: z.number().int(),
  end_column: z.number().int(),
  severity: z.enum(["error", "warning"]),
});
export type DslIssue = z.infer<typeof dslIssueSchema>;

export const validationResultSchema = z.object({
  valid: z.boolean(),
  issues: z.array(dslIssueSchema),
  ast: authorizationModelSchema.nullable(),
  formatted: z.string().nullable(),
});
export type ValidationResult = z.infer<typeof validationResultSchema>;

export const tupleKeySchema = z.object({
  object: z.string(),
  relation: z.string(),
  user: z.string(),
});
export type TupleKey = z.infer<typeof tupleKeySchema>;

export const storedTupleSchema = tupleKeySchema.extend({
  id: z.number().int(),
  created_revision: z.number().int(),
  created_at: z.string(),
});
export type StoredTuple = z.infer<typeof storedTupleSchema>;

export const tuplePageSchema = pageOf(storedTupleSchema).extend({ revision: z.number().int() });
export type TuplePage = z.infer<typeof tuplePageSchema>;

export const tupleChangeSchema = z.object({
  operation: z.enum(["write", "delete"]),
  revision: z.number().int(),
  tuple_key: tupleKeySchema,
});
export type TupleChange = z.infer<typeof tupleChangeSchema>;

export const writeResultSchema = z.object({
  revision: z.number().int(),
  consistency_token: z.string(),
  model_id: z.string(),
  written: z.number().int(),
  deleted: z.number().int(),
});
export type WriteResult = z.infer<typeof writeResultSchema>;

export const traceKinds = [
  "check",
  "direct",
  "computed",
  "tuple_to_userset",
  "union",
  "intersection",
  "exclusion",
  "tuple",
  "cycle",
] as const;
export type TraceKind = (typeof traceKinds)[number];
export type TraceResult = "allowed" | "denied" | "skipped";

export type TraceNode = {
  kind: TraceKind;
  label: string;
  result: TraceResult;
  object: string | null;
  relation: string | null;
  tuple_key: string | null;
  role: "base" | "subtract" | null;
  /** Answered from the shared check cache. */
  cached: boolean;
  /** A repeat of a sub-problem resolved elsewhere in the same trace. */
  memoized: boolean;
  duration_ms: number | null;
  children: TraceNode[];
};

export const traceNodeSchema: z.ZodType<TraceNode> = z.lazy(() =>
  z.object({
    kind: z.enum(traceKinds),
    label: z.string(),
    result: z.enum(["allowed", "denied", "skipped"]),
    object: z.string().nullable(),
    relation: z.string().nullable(),
    tuple_key: z.string().nullable(),
    role: z.enum(["base", "subtract"]).nullable(),
    cached: z.boolean(),
    memoized: z.boolean().default(false),
    duration_ms: z.number().nullable(),
    children: z.array(traceNodeSchema),
  }),
);

const resolutionSchema = z.object({
  model_id: z.string(),
  revision: z.number().int(),
  consistency_token: z.string(),
  duration_ms: z.number(),
});

export const checkResponseSchema = resolutionSchema.extend({
  allowed: z.boolean(),
  decision_id: z.string(),
  cached: z.boolean(),
  trace: traceNodeSchema,
  stats: z.object({
    dispatches: z.number().int(),
    memo_hits: z.number().int(),
    cache_hits: z.number().int(),
    queries: z.number().int(),
  }),
});
export type CheckResponse = z.infer<typeof checkResponseSchema>;

export const expandKinds = [
  "userset",
  "ref",
  "direct",
  "computed",
  "tuple_to_userset",
  "union",
  "intersection",
  "exclusion",
  "subject",
] as const;
export type ExpandKind = (typeof expandKinds)[number];

export type ExpandNode = {
  kind: ExpandKind;
  label: string;
  object: string | null;
  relation: string | null;
  subject: string | null;
  children: ExpandNode[];
};

export const expandNodeSchema: z.ZodType<ExpandNode> = z.lazy(() =>
  z.object({
    kind: z.enum(expandKinds),
    label: z.string(),
    object: z.string().nullable(),
    relation: z.string().nullable(),
    subject: z.string().nullable(),
    children: z.array(expandNodeSchema),
  }),
);

export const expandResponseSchema = resolutionSchema.extend({ tree: expandNodeSchema });
export type ExpandResponse = z.infer<typeof expandResponseSchema>;

export const listObjectsResponseSchema = resolutionSchema.extend({
  objects: z.array(z.string()),
  truncated: z.boolean(),
  decision_id: z.string(),
});
export type ListObjectsResponse = z.infer<typeof listObjectsResponseSchema>;

export const listUsersResponseSchema = resolutionSchema.extend({
  users: z.array(z.string()),
  truncated: z.boolean(),
  decision_id: z.string(),
});
export type ListUsersResponse = z.infer<typeof listUsersResponseSchema>;

export const decisionKinds = ["check", "list_objects", "list_users"] as const;

export const decisionSummarySchema = z.object({
  id: z.string(),
  store_id: z.string(),
  model_id: z.string(),
  revision: z.number().int(),
  kind: z.enum(decisionKinds),
  object: z.string(),
  relation: z.string(),
  subject: z.string(),
  allowed: z.boolean().nullable(),
  result_count: z.number().int().nullable(),
  duration_ms: z.number(),
  cached: z.boolean(),
  contextual_tuples: z.number().int(),
  api_key_id: z.string().nullable(),
  created_at: z.string(),
});
export type DecisionSummary = z.infer<typeof decisionSummarySchema>;

export const decisionSchema = decisionSummarySchema.extend({
  trace: traceNodeSchema.nullable(),
});
export type Decision = z.infer<typeof decisionSchema>;

export const decisionStatsSchema = z.object({
  window_hours: z.number().int(),
  total: z.number().int(),
  allowed: z.number().int(),
  denied: z.number().int(),
  list_queries: z.number().int(),
  allow_rate: z.number(),
  p50_ms: z.number(),
  p95_ms: z.number(),
  cached_rate: z.number(),
  timeline: z.array(
    z.object({ bucket: z.string(), allowed: z.number().int(), denied: z.number().int() }),
  ),
});
export type DecisionStats = z.infer<typeof decisionStatsSchema>;

export const storeOverviewSchema = z.object({
  store: storeSchema,
  latest_model: modelSummarySchema.nullable(),
  model_count: z.number().int(),
  tuple_count: z.number().int(),
  tuples_by_type: z.record(z.string(), z.number().int()),
  decisions: decisionStatsSchema,
  cache: z.object({
    scope: z.literal("service"),
    backend: z.enum(["memory", "redis", "none"]),
    hits: z.number().int(),
    misses: z.number().int(),
    hit_rate: z.number(),
  }),
});
export type StoreOverview = z.infer<typeof storeOverviewSchema>;

export const apiErrorSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    details: z.array(z.record(z.string(), z.unknown())),
  }),
});

export type ConsistencyMode =
  | "minimize_latency"
  | "at_least_as_fresh"
  | "at_exact_snapshot"
  | "fully_consistent";
