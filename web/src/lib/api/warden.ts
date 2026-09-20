import { z } from "zod";
import { requestJson, send } from "@/lib/api/client";
import {
  checkResponseSchema,
  decisionSchema,
  decisionSummarySchema,
  expandResponseSchema,
  listObjectsResponseSchema,
  listUsersResponseSchema,
  modelDetailSchema,
  modelSummarySchema,
  pageOf,
  storeOverviewSchema,
  storeSchema,
  tupleChangeSchema,
  tuplePageSchema,
  validationResultSchema,
  writeResultSchema,
  type ConsistencyMode,
  type TupleKey,
} from "@/lib/api/schemas";

const BASE = "/api/warden";

export interface ConsistencyInput {
  mode: ConsistencyMode;
  token?: string;
}

export interface CheckInput {
  tuple_key: TupleKey;
  contextual_tuples: TupleKey[];
  consistency: ConsistencyInput;
  explain: boolean;
}

export interface TupleFilter {
  object_type?: string;
  object_id?: string;
  relation?: string;
  user?: string;
}

export interface DecisionFilter {
  allowed?: boolean;
  subject?: string;
  object?: string;
}

const store = (id: string) => `v1/stores/${encodeURIComponent(id)}`;

export const warden = {
  stores: () => requestJson(BASE, "v1/stores", pageOf(storeSchema), { query: { limit: 100 } }),
  createStore: (name: string) =>
    requestJson(BASE, "v1/stores", storeSchema, { method: "POST", body: { name } }),
  overview: (storeId: string) => requestJson(BASE, `${store(storeId)}/overview`, storeOverviewSchema),

  models: (storeId: string) =>
    requestJson(BASE, `${store(storeId)}/models`, pageOf(modelSummarySchema), {
      query: { limit: 50 },
    }),
  model: (storeId: string, modelId: string) =>
    requestJson(BASE, `${store(storeId)}/models/${encodeURIComponent(modelId)}`, modelDetailSchema),
  latestModel: (storeId: string) =>
    requestJson(BASE, `${store(storeId)}/models/latest`, modelDetailSchema),
  writeModel: (storeId: string, dsl: string) =>
    requestJson(BASE, `${store(storeId)}/models`, modelDetailSchema, {
      method: "POST",
      body: { dsl },
    }),
  validate: (dsl: string, signal?: AbortSignal) =>
    requestJson(BASE, "v1/dsl/validate", validationResultSchema, {
      method: "POST",
      body: { dsl },
      ...(signal ? { signal } : {}),
    }),

  tuples: (storeId: string, filter: TupleFilter, cursor: string | null) =>
    requestJson(BASE, `${store(storeId)}/tuples`, tuplePageSchema, {
      query: { ...filter, cursor, limit: 50 },
    }),
  changes: (storeId: string, cursor: string | null) =>
    requestJson(BASE, `${store(storeId)}/changes`, pageOf(tupleChangeSchema), {
      query: { cursor, limit: 50 },
    }),
  writeTuples: (storeId: string, writes: TupleKey[], deletes: TupleKey[]) =>
    requestJson(BASE, `${store(storeId)}/tuples/write`, writeResultSchema, {
      method: "POST",
      body: { writes, deletes },
    }),

  check: (storeId: string, input: CheckInput) =>
    requestJson(BASE, `${store(storeId)}/check`, checkResponseSchema, {
      method: "POST",
      body: input,
    }),
  expand: (storeId: string, input: { object: string; relation: string }) =>
    requestJson(BASE, `${store(storeId)}/expand`, expandResponseSchema, {
      method: "POST",
      body: input,
    }),
  listObjects: (
    storeId: string,
    input: { object_type: string; relation: string; user: string; contextual_tuples: TupleKey[] },
  ) =>
    requestJson(BASE, `${store(storeId)}/list-objects`, listObjectsResponseSchema, {
      method: "POST",
      body: input,
    }),
  listUsers: (storeId: string, input: { object: string; relation: string; user_type: string }) =>
    requestJson(BASE, `${store(storeId)}/list-users`, listUsersResponseSchema, {
      method: "POST",
      body: input,
    }),

  decisions: (storeId: string, filter: DecisionFilter, cursor: string | null) =>
    requestJson(BASE, `${store(storeId)}/decisions`, pageOf(decisionSummarySchema), {
      query: { ...filter, cursor, limit: 50 },
    }),
  decision: (storeId: string, decisionId: string) =>
    requestJson(
      BASE,
      `${store(storeId)}/decisions/${encodeURIComponent(decisionId)}`,
      decisionSchema,
    ),
  health: async () => {
    const response = await send(BASE, "healthz");
    return z.object({ status: z.string(), version: z.string() }).parse(await response.json());
  },
};
