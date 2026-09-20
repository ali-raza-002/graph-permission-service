import { describe, expect, it } from "vitest";
import type { AuthorizationModel, ExpandNode, TraceNode } from "@/lib/api/schemas";
import { decisivePath, expandToGraph, layout, modelToGraph, traceToGraph } from "@/lib/graph";

const node = (partial: Partial<TraceNode> & Pick<TraceNode, "kind" | "label" | "result">): TraceNode => ({
  object: null,
  relation: null,
  tuple_key: null,
  role: null,
  cached: false,
  memoized: false,
  duration_ms: null,
  children: [],
  ...partial,
});

const trace = node({
  kind: "check",
  label: "document:roadmap#viewer",
  result: "allowed",
  children: [
    node({
      kind: "union",
      label: "or",
      result: "allowed",
      children: [
        node({ kind: "direct", label: "[user]", result: "denied" }),
        node({
          kind: "computed",
          label: "editor",
          result: "allowed",
          children: [
            node({
              kind: "check",
              label: "document:roadmap#editor",
              result: "allowed",
              children: [node({ kind: "tuple", label: "document:roadmap#editor@user:anne", result: "allowed" })],
            }),
          ],
        }),
        node({ kind: "tuple_to_userset", label: "viewer from parent", result: "skipped" }),
      ],
    }),
  ],
});

describe("traceToGraph", () => {
  it("folds computed steps into labelled edges", () => {
    const graph = traceToGraph(trace);
    expect(graph.nodes.map((n) => n.kind)).toEqual(["Check", "Union", "Direct", "Check", "Tuple", "Tuple to userset"]);
    const folded = graph.edges.find((e) => e.label === "editor");
    expect(folded?.source).toBe("0.0");
    expect(graph.edges.find((e) => e.tone === "skipped")?.dashed).toBe(true);
    expect(graph.nodes.filter((n) => n.root)).toHaveLength(1);
  });

  it("keeps only the branches that decided a grant", () => {
    const pruned = traceToGraph(decisivePath(trace));
    expect(pruned.nodes.map((n) => n.label)).toEqual([
      "document:roadmap#viewer",
      "or",
      "document:roadmap#editor",
      "document:roadmap#editor@user:anne",
    ]);
  });
});

describe("expandToGraph", () => {
  it("turns references into edges back to the expanded userset", () => {
    const leaf = (subject: string): ExpandNode => ({
      kind: "subject",
      label: subject,
      object: null,
      relation: null,
      subject,
      children: [],
    });
    const tree: ExpandNode = {
      kind: "userset",
      label: "group:a#member",
      object: "group:a",
      relation: "member",
      subject: null,
      children: [
        {
          kind: "direct",
          label: "[user, group#member]",
          object: null,
          relation: null,
          subject: null,
          children: [
            leaf("user:anne"),
            { kind: "ref", label: "group:a#member", object: "group:a", relation: "member", subject: null, children: [] },
          ],
        },
      ],
    };
    const graph = expandToGraph(tree);
    expect(graph.nodes).toHaveLength(3);
    const back = graph.edges.find((e) => e.label === "ref");
    expect(back).toMatchObject({ source: "0.0", target: "0", dashed: true });
  });
});

describe("modelToGraph", () => {
  it("links relations through computed, tuple-to-userset and userset edges", () => {
    const model: AuthorizationModel = {
      schema_version: "1.1",
      types: [
        { name: "user", relations: [] },
        {
          name: "folder",
          relations: [{ name: "viewer", rewrite: { kind: "direct", types: [{ type: "user", relation: null, wildcard: false }] } }],
        },
        {
          name: "document",
          relations: [
            {
              name: "parent",
              rewrite: { kind: "direct", types: [{ type: "folder", relation: null, wildcard: false }] },
            },
            {
              name: "viewer",
              rewrite: {
                kind: "union",
                children: [
                  { kind: "direct", types: [{ type: "user", relation: null, wildcard: true }] },
                  { kind: "tuple_to_userset", tupleset: "parent", computed: "viewer" },
                ],
              },
            },
          ],
        },
      ],
    };
    const graph = modelToGraph(model);
    const ids = graph.nodes.map((n) => n.id);
    expect(ids).toEqual(expect.arrayContaining(["user", "folder#viewer", "document#viewer", "user:*"]));
    expect(graph.edges.find((e) => e.label === "via parent")).toMatchObject({
      source: "folder#viewer",
      target: "document#viewer",
    });
    const positions = layout(graph, "LR");
    expect(new Set(positions.map((p) => `${p.x},${p.y}`)).size).toBe(positions.length);
  });
});
