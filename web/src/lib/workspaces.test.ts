import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api/client";
import type { Folder } from "@/lib/api/workspaces";
import { deniedDecisionId, describeSubject, folderTree } from "@/lib/workspaces";

const folder = (id: string, name: string, parent_id: string | null = null): Folder => ({
  id,
  name,
  parent_id,
  org_id: "lumen",
  description: "",
});

describe("folderTree", () => {
  it("nests children under visible parents in name order", () => {
    const tree = folderTree([
      folder("rfcs", "RFCs", "eng"),
      folder("eng", "Engineering"),
      folder("design", "Design"),
      folder("incidents", "Incident Reviews", "eng"),
    ]);
    expect(tree.map((e) => [e.folder.id, e.depth])).toEqual([
      ["design", 0],
      ["eng", 0],
      ["incidents", 1],
      ["rfcs", 1],
    ]);
  });

  it("promotes folders whose parent is not visible", () => {
    const tree = folderTree([folder("rfcs", "RFCs", "eng")]);
    expect(tree).toEqual([{ folder: folder("rfcs", "RFCs", "eng"), depth: 0 }]);
  });
});

describe("describeSubject", () => {
  const users = [{ handle: "anne", name: "Anne Liu", title: "Staff Engineer", email: "anne@lumen.dev" }];
  const teams = [{ id: "platform", name: "Platform", org_id: "lumen" }];

  it("labels users, teams, orgs and the public wildcard", () => {
    expect(describeSubject("user:anne", users, teams)).toMatchObject({ kind: "user", label: "Anne Liu", initials: "AL" });
    expect(describeSubject("team:platform#member", users, teams)).toMatchObject({ kind: "team", label: "Platform team" });
    expect(describeSubject("org:lumen#member", users, teams).kind).toBe("org");
    expect(describeSubject("user:*", users, teams).kind).toBe("public");
  });

  it("falls back to the raw handle for unknown users", () => {
    expect(describeSubject("user:zoe", users, teams).label).toBe("zoe");
  });
});

describe("deniedDecisionId", () => {
  it("reads the decision id from a 403", () => {
    const error = new ApiError(403, "forbidden", "no", [{ decision_id: "dc_1" }]);
    expect(deniedDecisionId(error)).toBe("dc_1");
  });

  it("ignores other failures", () => {
    expect(deniedDecisionId(new ApiError(404, "not_found", "gone"))).toBeNull();
    expect(deniedDecisionId(new Error("boom"))).toBeNull();
  });
});
