"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { workspaces, type Share } from "@/lib/api/workspaces";

const keys = {
  users: ["ws", "users"] as const,
  teams: ["ws", "teams"] as const,
  folders: (user: string) => ["ws", user, "folders"] as const,
  folder: (user: string, id: string) => ["ws", user, "folder", id] as const,
  document: (user: string, id: string) => ["ws", user, "document", id] as const,
  access: (user: string, id: string) => ["ws", user, "access", id] as const,
};

const noRetryOn4xx = (count: number, error: Error) =>
  !("status" in error && typeof error.status === "number" && error.status < 500) && count < 2;

export function useWorkspaceUsers() {
  return useQuery({ queryKey: keys.users, queryFn: workspaces.users, staleTime: Infinity });
}

export function useTeams() {
  return useQuery({ queryKey: keys.teams, queryFn: workspaces.teams, staleTime: Infinity });
}

export function useFolders(user: string | null) {
  return useQuery({
    queryKey: keys.folders(user ?? ""),
    queryFn: () => workspaces.folders(user ?? ""),
    enabled: user !== null,
  });
}

export function useFolder(user: string | null, folderId: string | null) {
  return useQuery({
    queryKey: keys.folder(user ?? "", folderId ?? ""),
    queryFn: () => workspaces.folder(user ?? "", folderId ?? ""),
    enabled: user !== null && folderId !== null,
    retry: noRetryOn4xx,
  });
}

export function useDocument(user: string | null, documentId: string | null) {
  return useQuery({
    queryKey: keys.document(user ?? "", documentId ?? ""),
    queryFn: () => workspaces.document(user ?? "", documentId ?? ""),
    enabled: user !== null && documentId !== null,
    retry: noRetryOn4xx,
  });
}

export function useAccess(user: string, documentId: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.access(user, documentId),
    queryFn: () => workspaces.access(user, documentId),
    enabled,
    retry: noRetryOn4xx,
  });
}

/** Any write can change what every user sees, so refresh all per-user views. */
function useInvalidateAll() {
  const client = useQueryClient();
  return () =>
    client.invalidateQueries({
      predicate: (query) => query.queryKey[0] === "ws" && query.queryKey[1] !== "users" && query.queryKey[1] !== "teams",
    });
}

export function useCreateDocument(user: string, folderId: string) {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: (input: { title: string; body: string }) => workspaces.createDocument(user, folderId, input),
    onSuccess: invalidate,
  });
}

export function useUpdateDocument(user: string, documentId: string) {
  const client = useQueryClient();
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: (input: { title: string; body: string }) => workspaces.updateDocument(user, documentId, input),
    onSuccess: async (detail) => {
      client.setQueryData(keys.document(user, documentId), detail);
      await invalidate();
    },
  });
}

export function useDeleteDocument(user: string, documentId: string) {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: () => workspaces.deleteDocument(user, documentId),
    onSuccess: invalidate,
  });
}

export function useShare(user: string, documentId: string) {
  const client = useQueryClient();
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({ share, remove }: { share: Share; remove: boolean }) =>
      remove ? workspaces.unshare(user, documentId, share) : workspaces.share(user, documentId, share),
    onSuccess: async (access) => {
      client.setQueryData(keys.access(user, documentId), access);
      await invalidate();
    },
  });
}
