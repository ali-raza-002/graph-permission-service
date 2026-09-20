import { ApiError } from "@/lib/api/client";
import type { Folder, Team, WorkspaceUser } from "@/lib/api/workspaces";

export interface FolderEntry {
  folder: Folder;
  depth: number;
}

/**
 * Flatten folders into display order with nesting depth. A folder whose parent the
 * user cannot see is shown at the top level rather than hidden.
 */
export function folderTree(folders: Folder[]): FolderEntry[] {
  const visible = new Set(folders.map((f) => f.id));
  const children = new Map<string | null, Folder[]>();
  for (const folder of folders) {
    const parent = folder.parent_id !== null && visible.has(folder.parent_id) ? folder.parent_id : null;
    const siblings = children.get(parent) ?? [];
    siblings.push(folder);
    children.set(parent, siblings);
  }
  const out: FolderEntry[] = [];
  const walk = (parent: string | null, depth: number) => {
    const level = [...(children.get(parent) ?? [])].sort((a, b) => a.name.localeCompare(b.name));
    for (const folder of level) {
      out.push({ folder, depth });
      walk(folder.id, depth + 1);
    }
  };
  walk(null, 0);
  return out;
}

export type SubjectKind = "user" | "team" | "org" | "public";

export interface SubjectLabel {
  kind: SubjectKind;
  label: string;
  detail: string;
  initials: string;
}

function initials(name: string): string {
  const parts = name.split(/\s+/).filter(Boolean);
  return parts.length > 1
    ? `${parts[0]?.[0] ?? ""}${parts[parts.length - 1]?.[0] ?? ""}`.toUpperCase()
    : name.slice(0, 2).toUpperCase();
}

export function describeSubject(subject: string, users: WorkspaceUser[], teams: Team[]): SubjectLabel {
  if (subject === "user:*") {
    return { kind: "public", label: "Everyone", detail: "Any signed-in user", initials: "*" };
  }
  const [ref = "", relation] = subject.split("#", 2);
  const [type = "", id = ""] = ref.split(":", 2);
  if (type === "user") {
    const user = users.find((u) => u.handle === id);
    const label = user?.name ?? id;
    return { kind: "user", label, detail: user?.title ?? subject, initials: initials(label) };
  }
  if (type === "team") {
    const label = teams.find((t) => t.id === id)?.name ?? id;
    return { kind: "team", label: `${label} team`, detail: `Members of ${subject}`, initials: initials(label) };
  }
  if (type === "org") {
    return {
      kind: "org",
      label: "Everyone at the org",
      detail: relation ? `${ref} ${relation}s` : ref,
      initials: id.slice(0, 2).toUpperCase(),
    };
  }
  return { kind: "user", label: subject, detail: subject, initials: initials(id || subject) };
}

/** The decision id Warden attached to a 403, so the UI can link to the trace. */
export function deniedDecisionId(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.status !== 403) return null;
  const id = error.details[0]?.["decision_id"];
  return typeof id === "string" ? id : null;
}
