"use client";

import "@xyflow/react/dist/style.css";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  useReactFlow,
  useStore,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { useEffect, useMemo } from "react";
import { usePrefersReducedMotion } from "@/hooks/use-reduced-motion";
import { layout, NODE_HEIGHT, NODE_WIDTH, type Graph, type GraphNode, type Tone } from "@/lib/graph";
import { cn } from "@/lib/utils";

/** Fits once the viewport is measured; the fitView prop can race and ignore `nodes`. */
function FitOnLayout({ focus }: { focus: { id: string }[] | undefined }) {
  const { fitView } = useReactFlow();
  const ready = useStore((s) => s.panZoom !== null && s.width > 0 && s.height > 0);
  useEffect(() => {
    if (ready) void fitView({ padding: 0.15, maxZoom: 1.1, ...(focus ? { nodes: focus } : {}) });
  }, [ready, focus, fitView]);
  return null;
}

const FOCUS_LEVELS = 5;

type FlowNode = Node<{ node: GraphNode; horizontal: boolean }, "warden">;

const TONE_STYLES: Record<Tone, { card: string; dot: string; text: string }> = {
  allowed: {
    card: "border-success/60 bg-card shadow-sm",
    dot: "bg-success",
    text: "text-[color-mix(in_oklab,var(--success)_70%,var(--foreground))]",
  },
  denied: { card: "border-border bg-card", dot: "bg-destructive", text: "text-destructive" },
  skipped: { card: "border-dashed border-border bg-card/60 opacity-70", dot: "bg-muted-foreground/40", text: "text-muted-foreground" },
  neutral: { card: "border-border bg-card", dot: "bg-primary", text: "text-muted-foreground" },
};

const RESULT_LABEL: Record<Tone, string | null> = {
  allowed: "Allowed",
  denied: "Denied",
  skipped: "Skipped",
  neutral: null,
};

function WardenNode({ data }: NodeProps<FlowNode>) {
  const { node, horizontal } = data;
  const tone = TONE_STYLES[node.tone];
  const result = RESULT_LABEL[node.tone];
  return (
    <div
      className={cn(
        "flex h-full w-full flex-col justify-center gap-1 rounded-xl border px-3 py-2 transition-shadow",
        tone.card,
        node.root && "ring-4 ring-ring/40",
      )}
      title={node.label}
    >
      <Handle
        type="target"
        position={horizontal ? Position.Left : Position.Top}
        className="size-1.5! border-0! bg-border!"
      />
      <div className="flex items-center gap-2">
        <span className="truncate text-[10.5px] font-medium tracking-wide text-muted-foreground uppercase">
          {node.kind}
        </span>
        {result ? (
          <span className={cn("ml-auto flex items-center gap-1 text-[11px] font-medium", tone.text)}>
            <span className={cn("size-1.5 rounded-full", tone.dot)} />
            {result}
          </span>
        ) : null}
      </div>
      <p className="truncate font-mono text-[12px] leading-4 text-foreground">{node.label}</p>
      {node.badges.length > 0 || node.detail ? (
        <p className="truncate text-[11px] text-muted-foreground">
          {[node.detail, ...node.badges].filter(Boolean).join(" · ")}
        </p>
      ) : null}
      <Handle
        type="source"
        position={horizontal ? Position.Right : Position.Bottom}
        className="size-1.5! border-0! bg-border!"
      />
    </div>
  );
}

const nodeTypes = { warden: WardenNode };

const EDGE_COLOR: Record<Tone, string> = {
  allowed: "var(--success)",
  denied: "var(--border)",
  skipped: "var(--border)",
  neutral: "color-mix(in oklab, var(--muted-foreground) 45%, transparent)",
};

export function FlowGraph({
  graph,
  direction = "TB",
  className,
  ariaLabel,
}: {
  graph: Graph;
  direction?: "TB" | "LR";
  className?: string;
  ariaLabel: string;
}) {
  const horizontal = direction === "LR";
  const reducedMotion = usePrefersReducedMotion();
  const { nodes, edges, focus } = useMemo(() => {
    const positioned = layout(graph, direction);
    const flowNodes: FlowNode[] = positioned.map(({ item, x, y }) => ({
      id: item.id,
      type: "warden",
      position: { x, y },
      data: { node: item, horizontal },
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
      draggable: false,
      connectable: false,
    }));
    const flowEdges: Edge[] = graph.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      type: "smoothstep",
      animated: edge.tone === "allowed" && !horizontal && !reducedMotion,
      ...(edge.label ? { label: edge.label } : {}),
      labelStyle: { fontSize: 11, fill: "var(--muted-foreground)" },
      labelBgStyle: { fill: "var(--background)" },
      style: {
        stroke: EDGE_COLOR[edge.tone],
        strokeWidth: edge.tone === "allowed" ? 2 : 1.25,
        ...(edge.dashed ? { strokeDasharray: "4 4" } : {}),
      },
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: EDGE_COLOR[edge.tone] },
    }));
    // Deep traces fit to their top levels so labels stay legible; the rest is a pan away.
    const levels = [...new Set(positioned.map((p) => (horizontal ? p.x : p.y)))].sort((a, b) => a - b);
    const cutoff = levels[Math.min(levels.length, FOCUS_LEVELS) - 1] ?? 0;
    const focus =
      levels.length > FOCUS_LEVELS + 1
        ? positioned.filter((p) => (horizontal ? p.x : p.y) <= cutoff).map((p) => ({ id: p.item.id }))
        : undefined;
    return { nodes: flowNodes, edges: flowEdges, focus };
  }, [graph, direction, horizontal, reducedMotion]);

  return (
    <div
      className={cn("h-[520px] w-full", className)}
      role="group"
      aria-roledescription="graph"
      aria-label={ariaLabel}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        minZoom={0.2}
        maxZoom={1.75}
        nodesDraggable={false}
        nodesConnectable={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="var(--border)" />
        <Controls
          showInteractive={false}
          position="bottom-right"
          fitViewOptions={{ padding: 0.15, maxZoom: 1.1 }}
        />
        <FitOnLayout focus={focus} />
      </ReactFlow>
    </div>
  );
}
