"use client";

import { ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";
import { FlowGraph } from "@/components/graph/flow-graph";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { TraceNode } from "@/lib/api/schemas";
import { countTrace, decisivePath, traceToGraph } from "@/lib/graph";

type Mode = "decisive" | "full";

const RESULT_TEXT = { allowed: "allowed", denied: "denied", skipped: "skipped" } as const;

function OutlineNode({ node }: { node: TraceNode }) {
  const notes = [node.kind.replaceAll("_", " "), RESULT_TEXT[node.result]];
  if (node.cached) notes.push("from cache");
  if (node.memoized) notes.push("resolved above");
  if (node.role) notes.push(node.role);
  return (
    <li className="space-y-1">
      <p className="text-[12.5px]">
        <span className="font-mono text-foreground">{node.label}</span>{" "}
        <span className="text-muted-foreground">({notes.join(", ")})</span>
      </p>
      {node.children.length > 0 ? (
        <ul className="space-y-1 border-l border-border pl-4">
          {node.children.map((child, index) => (
            <OutlineNode key={`${child.kind}:${child.label}:${index}`} node={child} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

/** The same trace as nested text, for screen readers and for copying into a ticket. */
function TraceOutline({ trace }: { trace: TraceNode }) {
  return (
    <details className="group rounded-xl border border-border/60 bg-card px-4 py-3">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[13px] font-medium select-none focus-visible:ring-4 focus-visible:ring-ring focus-visible:outline-none">
        <ChevronRight className="size-4 transition-transform group-open:rotate-90 motion-reduce:transition-none" strokeWidth={1.75} />
        Text outline
      </summary>
      <ul className="mt-3 space-y-1">
        <OutlineNode node={trace} />
      </ul>
    </details>
  );
}

export function TraceView({ trace, className }: { trace: TraceNode; className?: string }) {
  const total = countTrace(trace);
  const [mode, setMode] = useState<Mode>(total > 18 ? "decisive" : "full");
  const shown = useMemo(() => (mode === "decisive" ? decisivePath(trace) : trace), [trace, mode]);
  const graph = useMemo(() => traceToGraph(shown), [shown]);
  const verdict = trace.result === "allowed" ? "granted" : "denied";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[13px] text-muted-foreground">
          {mode === "decisive"
            ? `The steps that ${verdict} access, out of ${total} evaluated.`
            : `All ${total} steps, including branches that were short-circuited.`}
        </p>
        <Tabs value={mode} onValueChange={(value) => setMode(value === "full" ? "full" : "decisive")}>
          <TabsList aria-label="Trace detail">
            <TabsTrigger value="decisive">Decisive path</TabsTrigger>
            <TabsTrigger value="full">Full trace</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>
      <div className="overflow-hidden rounded-xl border border-border/60 bg-background">
        <FlowGraph
          graph={graph}
          {...(className ? { className } : {})}
          ariaLabel={`Resolution graph for ${trace.label}: ${trace.result}. A text outline follows.`}
        />
      </div>
      <TraceOutline trace={shown} />
    </div>
  );
}
