import dagre from "@dagrejs/dagre";
import type { AuthorizationModel, ExpandNode, Rewrite, TraceNode } from "@/lib/api/schemas";

export type Tone = "allowed" | "denied" | "skipped" | "neutral";

export interface GraphNode {
  id: string;
  kind: string;
  label: string;
  tone: Tone;
  detail: string | null;
  badges: string[];
  root: boolean;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  tone: Tone;
  dashed: boolean;
  label: string | null;
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Positioned<T> {
  item: T;
  x: number;
  y: number;
}

export const NODE_WIDTH = 236;
export const NODE_HEIGHT = 74;

const TRACE_KIND_LABEL: Record<string, string> = {
  check: "Check",
  direct: "Direct",
  computed: "Computed",
  tuple_to_userset: "Tuple to userset",
  union: "Union",
  intersection: "Intersection",
  exclusion: "Exclusion",
  tuple: "Tuple",
  cycle: "Cycle",
};

export function traceKindLabel(kind: string): string {
  return TRACE_KIND_LABEL[kind] ?? kind;
}

/** Keep only the branches that decided the result, which is the "why" of a grant. */
export function decisivePath(node: TraceNode): TraceNode {
  const decisive =
    node.result === "allowed"
      ? node.children.filter((c) => c.result === "allowed" || (c.role === "subtract" && c.result === "denied"))
      : node.children.filter((c) => c.result !== "skipped");
  return { ...node, children: decisive.map(decisivePath) };
}

export function countTrace(node: TraceNode): number {
  return 1 + node.children.reduce((sum, child) => sum + countTrace(child), 0);
}

/**
 * Flatten a trace tree into graph nodes. Computed-userset steps only point at another
 * check on the same object, so they are folded into the edge to keep graphs readable.
 */
export function traceToGraph(root: TraceNode): Graph {
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];

  const visit = (node: TraceNode, id: string, parent: string | null, via: string | null) => {
    if (node.kind === "computed" && node.children.length === 1 && parent !== null) {
      const [child] = node.children;
      if (child) {
        visit(child, `${id}.0`, parent, node.label);
        return;
      }
    }
    const badges: string[] = [];
    if (node.cached) badges.push("cached");
    if (node.memoized) badges.push("seen above");
    if (node.role) badges.push(node.role);
    if (node.duration_ms !== null && node.kind === "check") badges.push(`${node.duration_ms.toFixed(1)} ms`);
    nodes.push({
      id,
      kind: traceKindLabel(node.kind),
      label: node.label,
      tone: node.result,
      detail: node.kind === "cycle" ? "Cycle cut, resolved by fixpoint" : null,
      badges,
      root: parent === null,
    });
    if (parent !== null) {
      edges.push({
        id: `${parent}->${id}`,
        source: parent,
        target: id,
        tone: node.result,
        dashed: node.result === "skipped" || node.role === "subtract",
        label: via,
      });
    }
    node.children.forEach((child, index) => visit(child, `${id}.${index}`, id, null));
  };

  visit(root, "0", null, null);
  return { nodes, edges };
}

/** Expansion graphs reference already-expanded usersets; draw those as edges back. */
export function expandToGraph(root: ExpandNode): Graph {
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];
  const usersets = new Map<string, string>();
  const refs: { parent: string; label: string; id: string }[] = [];

  const visit = (node: ExpandNode, id: string, parent: string | null) => {
    if (node.kind === "ref" && parent !== null) {
      refs.push({ parent, label: node.label, id });
      return;
    }
    if (node.kind === "userset") usersets.set(node.label, id);
    nodes.push({
      id,
      kind: node.kind === "subject" ? "Subject" : traceKindLabel(node.kind === "userset" ? "check" : node.kind),
      label: node.kind === "subject" ? (node.subject ?? node.label) : node.label,
      tone: node.kind === "subject" ? "allowed" : "neutral",
      detail: null,
      badges: [],
      root: parent === null,
    });
    if (parent !== null) {
      edges.push({ id: `${parent}->${id}`, source: parent, target: id, tone: "neutral", dashed: false, label: null });
    }
    node.children.forEach((child, index) => visit(child, `${id}.${index}`, id));
  };

  visit(root, "0", null);
  for (const ref of refs) {
    const target = usersets.get(ref.label);
    if (target) {
      edges.push({
        id: `${ref.parent}~>${target}:${ref.id}`,
        source: ref.parent,
        target,
        tone: "neutral",
        dashed: true,
        label: "ref",
      });
    }
  }
  return { nodes, edges };
}

function rewriteEdges(
  type: string,
  relation: string,
  rewrite: Rewrite,
  model: AuthorizationModel,
  out: GraphEdge[],
) {
  const target = `${type}#${relation}`;
  switch (rewrite.kind) {
    case "direct":
      for (const r of rewrite.types) {
        const source = r.relation ? `${r.type}#${r.relation}` : r.wildcard ? `${r.type}:*` : r.type;
        out.push({ id: `${source}->${target}:direct`, source, target, tone: "neutral", dashed: false, label: null });
      }
      return;
    case "computed":
      out.push({
        id: `${type}#${rewrite.relation}->${target}`,
        source: `${type}#${rewrite.relation}`,
        target,
        tone: "allowed",
        dashed: false,
        label: null,
      });
      return;
    case "tuple_to_userset": {
      const parentTypes = model.types
        .find((t) => t.name === type)
        ?.relations.find((r) => r.name === rewrite.tupleset);
      const parents =
        parentTypes?.rewrite.kind === "direct" ? parentTypes.rewrite.types.map((t) => t.type) : [];
      for (const parent of parents) {
        out.push({
          id: `${parent}#${rewrite.computed}->${target}:ttu`,
          source: `${parent}#${rewrite.computed}`,
          target,
          tone: "allowed",
          dashed: true,
          label: `via ${rewrite.tupleset}`,
        });
      }
      return;
    }
    case "union":
    case "intersection":
      rewrite.children.forEach((child) => rewriteEdges(type, relation, child, model, out));
      return;
    case "exclusion":
      rewriteEdges(type, relation, rewrite.base, model, out);
      return;
  }
}

/** Relation dependency graph: which usersets feed which relation. */
export function modelToGraph(model: AuthorizationModel): Graph {
  const nodes = new Map<string, GraphNode>();
  const edges: GraphEdge[] = [];
  for (const type of model.types) {
    if (type.relations.length === 0) {
      nodes.set(type.name, {
        id: type.name,
        kind: "Type",
        label: type.name,
        tone: "neutral",
        detail: null,
        badges: [],
        root: false,
      });
    }
    for (const relation of type.relations) {
      const id = `${type.name}#${relation.name}`;
      nodes.set(id, { id, kind: type.name, label: relation.name, tone: "neutral", detail: null, badges: [], root: false });
      rewriteEdges(type.name, relation.name, relation.rewrite, model, edges);
    }
  }
  for (const edge of edges) {
    if (!nodes.has(edge.source)) {
      nodes.set(edge.source, {
        id: edge.source,
        kind: "Type",
        label: edge.source,
        tone: "neutral",
        detail: null,
        badges: [],
        root: false,
      });
    }
  }
  const unique = new Map(edges.filter((e) => nodes.has(e.target)).map((e) => [e.id, e]));
  return { nodes: [...nodes.values()], edges: [...unique.values()] };
}

export function layout(
  graph: Graph,
  direction: "TB" | "LR" = "TB",
  size: { width: number; height: number } = { width: NODE_WIDTH, height: NODE_HEIGHT },
): Positioned<GraphNode>[] {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: direction, nodesep: 28, ranksep: direction === "TB" ? 56 : 90, marginx: 16, marginy: 16 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const node of graph.nodes) g.setNode(node.id, { width: size.width, height: size.height });
  for (const edge of graph.edges) g.setEdge(edge.source, edge.target);
  dagre.layout(g);
  return graph.nodes.map((item) => {
    const position = g.node(item.id);
    return {
      item,
      x: (position?.x ?? 0) - size.width / 2,
      y: (position?.y ?? 0) - size.height / 2,
    };
  });
}
