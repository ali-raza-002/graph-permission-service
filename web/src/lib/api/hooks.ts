"use client";

import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type { TupleKey } from "@/lib/api/schemas";
import { warden, type DecisionFilter, type TupleFilter } from "@/lib/api/warden";

export const keys = {
  stores: ["stores"] as const,
  overview: (storeId: string) => ["overview", storeId] as const,
  models: (storeId: string) => ["models", storeId] as const,
  model: (storeId: string, modelId: string) => ["model", storeId, modelId] as const,
  latestModel: (storeId: string) => ["model", storeId, "latest"] as const,
  tuples: (storeId: string, filter: TupleFilter) => ["tuples", storeId, filter] as const,
  changes: (storeId: string) => ["changes", storeId] as const,
  decisions: (storeId: string, filter: DecisionFilter) => ["decisions", storeId, filter] as const,
  decision: (storeId: string, decisionId: string) => ["decision", storeId, decisionId] as const,
};

export function useStores() {
  return useQuery({ queryKey: keys.stores, queryFn: warden.stores });
}

export function useOverview(storeId: string) {
  return useQuery({
    queryKey: keys.overview(storeId),
    queryFn: () => warden.overview(storeId),
    refetchInterval: 15_000,
  });
}

export function useModels(storeId: string) {
  return useQuery({ queryKey: keys.models(storeId), queryFn: () => warden.models(storeId) });
}

export function useLatestModel(storeId: string) {
  return useQuery({
    queryKey: keys.latestModel(storeId),
    queryFn: () => warden.latestModel(storeId),
    retry: false,
  });
}

export function useModel(storeId: string, modelId: string | null) {
  return useQuery({
    queryKey: keys.model(storeId, modelId ?? "none"),
    queryFn: () => warden.model(storeId, modelId ?? ""),
    enabled: modelId !== null,
  });
}

export function useWriteModel(storeId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (dsl: string) => warden.writeModel(storeId, dsl),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: keys.models(storeId) }),
        client.invalidateQueries({ queryKey: ["model", storeId] }),
        client.invalidateQueries({ queryKey: keys.overview(storeId) }),
      ]);
    },
  });
}

export function useTuples(storeId: string, filter: TupleFilter) {
  return useInfiniteQuery({
    queryKey: keys.tuples(storeId, filter),
    queryFn: ({ pageParam }) => warden.tuples(storeId, filter, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
  });
}

export function useChanges(storeId: string) {
  return useInfiniteQuery({
    queryKey: keys.changes(storeId),
    queryFn: ({ pageParam }) => warden.changes(storeId, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
}

export function useWriteTuples(storeId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ writes = [], deletes = [] }: { writes?: TupleKey[]; deletes?: TupleKey[] }) =>
      warden.writeTuples(storeId, writes, deletes),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ["tuples", storeId] }),
        client.invalidateQueries({ queryKey: keys.changes(storeId) }),
        client.invalidateQueries({ queryKey: keys.overview(storeId) }),
      ]);
    },
  });
}

export function useDecisions(storeId: string, filter: DecisionFilter, { poll = true }: { poll?: boolean } = {}) {
  return useInfiniteQuery({
    queryKey: keys.decisions(storeId, filter),
    queryFn: ({ pageParam }) => warden.decisions(storeId, filter, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: keepPreviousData,
    refetchInterval: poll ? 10_000 : false,
  });
}

export function useDecision(storeId: string, decisionId: string | null) {
  return useQuery({
    queryKey: keys.decision(storeId, decisionId ?? "none"),
    queryFn: () => warden.decision(storeId, decisionId ?? ""),
    enabled: decisionId !== null,
  });
}
