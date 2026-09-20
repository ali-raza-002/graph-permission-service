import { z } from "zod";
import { requestJson, send } from "@/lib/api/client";

const BASE = "/api/workspaces";

export const WORKSPACES_STORE_ID = process.env.NEXT_PUBLIC_WORKSPACES_STORE_ID ?? "st_workspaces_demo";

export const userSchema = z.object({
  handle: z.string(),
  name: z.string(),
  title: z.string(),
  email: z.string(),
});
export type WorkspaceUser = z.infer<typeof userSchema>;

export const teamSchema = z.object({ id: z.string(), name: z.string(), org_id: z.string() });
export type Team = z.infer<typeof teamSchema>;

export const folderSchema = z.object({
  id: z.string(),
  org_id: z.string(),
  parent_id: z.string().nullable(),
  name: z.string(),
  description: z.string(),
});
export type Folder = z.infer<typeof folderSchema>;

const documentSummarySchema = z.object({
  id: z.string(),
  folder_id: z.string(),
  title: z.string(),
  created_by: z.string(),
  updated_at: z.string(),
});
export type DocumentSummary = z.infer<typeof documentSummarySchema>;

const authorizationSchema = z.object({
  decision_id: z.string(),
  revision: z.number().int(),
  duration_ms: z.number(),
});
export type Authorization = z.infer<typeof authorizationSchema>;

export const folderDetailSchema = z.object({
  folder: folderSchema,
  documents: z.array(documentSummarySchema),
  can_create: z.boolean(),
  authorization: authorizationSchema,
});
export type FolderDetail = z.infer<typeof folderDetailSchema>;

export const documentDetailSchema = z.object({
  document: documentSummarySchema.extend({ body: z.string(), created_at: z.string() }),
  permissions: z.object({ can_edit: z.boolean(), can_share: z.boolean(), can_delete: z.boolean() }),
  authorization: authorizationSchema,
});
export type DocumentDetail = z.infer<typeof documentDetailSchema>;

export const roles = ["viewer", "editor", "blocked"] as const;
export type Role = (typeof roles)[number];

export const shareSchema = z.object({ subject: z.string(), role: z.enum(roles) });
export type Share = z.infer<typeof shareSchema>;

export const accessSchema = z.object({
  owner: z.array(z.string()),
  shares: z.array(shareSchema),
  effective_viewers: z.array(z.string()),
  can_share: z.boolean(),
  can_manage: z.boolean(),
});
export type Access = z.infer<typeof accessSchema>;

const as = (user: string) => ({ "x-workspaces-user": user });
const doc = (id: string) => `api/documents/${encodeURIComponent(id)}`;

export const workspaces = {
  users: () => requestJson(BASE, "api/users", z.array(userSchema)),
  teams: () => requestJson(BASE, "api/teams", z.array(teamSchema)),
  folders: (user: string) =>
    requestJson(BASE, "api/folders", z.array(folderSchema), { headers: as(user) }),
  folder: (user: string, folderId: string) =>
    requestJson(BASE, `api/folders/${encodeURIComponent(folderId)}`, folderDetailSchema, {
      headers: as(user),
    }),
  document: (user: string, documentId: string) =>
    requestJson(BASE, doc(documentId), documentDetailSchema, { headers: as(user) }),
  createDocument: (user: string, folderId: string, input: { title: string; body: string }) =>
    requestJson(BASE, `api/folders/${encodeURIComponent(folderId)}/documents`, documentDetailSchema, {
      method: "POST",
      headers: as(user),
      body: input,
    }),
  updateDocument: (user: string, documentId: string, input: { title: string; body: string }) =>
    requestJson(BASE, doc(documentId), documentDetailSchema, {
      method: "PATCH",
      headers: as(user),
      body: input,
    }),
  deleteDocument: async (user: string, documentId: string) => {
    await send(BASE, doc(documentId), { method: "DELETE", headers: as(user) });
  },
  access: (user: string, documentId: string) =>
    requestJson(BASE, `${doc(documentId)}/access`, accessSchema, { headers: as(user) }),
  share: (user: string, documentId: string, share: Share) =>
    requestJson(BASE, `${doc(documentId)}/shares`, accessSchema, {
      method: "POST",
      headers: as(user),
      body: share,
    }),
  unshare: (user: string, documentId: string, share: Share) =>
    requestJson(BASE, `${doc(documentId)}/unshare`, accessSchema, {
      method: "POST",
      headers: as(user),
      body: share,
    }),
};
