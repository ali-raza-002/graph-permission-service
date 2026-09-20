"use client";

import { AlertTriangle, CheckCircle2, Loader2, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { DslEditor, type DslEditorHandle } from "@/components/console/dsl-editor";
import { ErrorNotice, PageBody, PageHeader, SectionLabel } from "@/components/console/page";
import { FlowGraph } from "@/components/graph/flow-graph";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError } from "@/lib/api/client";
import { useLatestModel, useModel, useModels, useWriteModel } from "@/lib/api/hooks";
import type { AuthorizationModel, DslIssue, ValidationResult } from "@/lib/api/schemas";
import { warden } from "@/lib/api/warden";
import { timeAgo } from "@/lib/format";
import { modelToGraph } from "@/lib/graph";
import { cn } from "@/lib/utils";

const STARTER = `model
  schema 1.1

type user

type document
  relations
    define owner: [user]
    define viewer: [user] or owner
`;

const CHEAT_SHEET: [string, string][] = [
  ["[user, group#member]", "Directly assignable subjects"],
  ["[user:*]", "Public: every user"],
  ["owner", "Everyone who has another relation"],
  ["viewer from parent", "Inherited through a parent object"],
  ["a or b", "Union"],
  ["a and b", "Intersection"],
  ["a but not b", "Exclusion"],
];

interface Validation {
  dsl: string;
  result: ValidationResult | null;
  error: Error | null;
}

// Pending is derived from which source the last response belongs to, so a keystroke never
// sets state synchronously; bursts of edits would otherwise trip React's nested-update limit.
function useLiveValidation(dsl: string) {
  const [validation, setValidation] = useState<Validation | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      warden
        .validate(dsl, controller.signal)
        .then((result) => setValidation({ dsl, result, error: null }))
        .catch((reason: unknown) => {
          if (reason instanceof DOMException && reason.name === "AbortError") return;
          setValidation({ dsl, result: null, error: reason instanceof Error ? reason : new Error("Validation failed") });
        });
    }, 350);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [dsl]);
  return {
    result: validation?.result ?? null,
    error: validation?.error ?? null,
    pending: validation?.dsl !== dsl,
  };
}

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

function Problems({ issues, onSelect }: { issues: DslIssue[]; onSelect: (issue: DslIssue) => void }) {
  if (issues.length === 0) return null;
  const hasErrors = issues.some((i) => i.severity === "error");
  return (
    <ul
      aria-label="Problems"
      className={cn(
        "divide-y divide-border rounded-xl border bg-card",
        hasErrors ? "border-destructive/25" : "border-warning/30",
      )}
    >
      {issues.map((issue) => (
        <li key={`${issue.line}:${issue.column}:${issue.code}`}>
          <button
            type="button"
            onClick={() => onSelect(issue)}
            className="flex w-full items-start gap-3 px-4 py-2.5 text-left text-[13px] transition-colors hover:bg-accent/50 focus-visible:bg-accent/50 focus-visible:ring-4 focus-visible:ring-ring focus-visible:outline-none"
          >
            <AlertTriangle
              className={cn("mt-0.5 size-4 shrink-0", issue.severity === "error" ? "text-destructive" : "text-warning")}
              strokeWidth={1.75}
              aria-label={issue.severity}
            />
            <span className="min-w-0 flex-1">{issue.message}</span>
            <span className="shrink-0 font-mono text-[12px] text-muted-foreground tabular-nums">
              {issue.line}:{issue.column}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function ModelGraph({ ast }: { ast: AuthorizationModel }) {
  const graph = useMemo(() => modelToGraph(ast), [ast]);
  return (
    <div className="overflow-hidden rounded-xl border border-border/60 bg-background">
      <FlowGraph graph={graph} direction="LR" className="h-[calc(100dvh-300px)] min-h-[420px]" ariaLabel="Relation dependency graph" />
    </div>
  );
}

export function ModelView({ storeId }: { storeId: string }) {
  const latest = useLatestModel(storeId);
  const versions = useModels(storeId);
  const write = useWriteModel(storeId);
  const [selected, setSelected] = useState<string | null>(null);
  const selectedModel = useModel(storeId, selected);
  const [draft, setDraft] = useState<string | null>(null);
  const editor = useRef<DslEditorHandle | null>(null);

  const base = selected ? selectedModel.data?.dsl : latest.data?.dsl;
  const noModel = latest.error instanceof ApiError && latest.error.status === 404;
  const source = draft ?? base ?? (noModel ? STARTER : "");
  const { result, error: validationError, pending } = useLiveValidation(source);
  const issues = result?.issues ?? [];
  const errorCount = issues.filter((i) => i.severity === "error").length;
  const warningCount = issues.length - errorCount;
  const dirty = latest.data ? source !== latest.data.dsl : source.trim().length > 0;
  const nextVersion = (latest.data?.version ?? 0) + 1;
  const canSave = dirty && result?.valid === true && !write.isPending;

  const save = () => {
    if (!canSave) return;
    write.mutate(source, {
      onSuccess: (model) => {
        toast.success(`Saved model v${model.version}`);
        setDraft(null);
        setSelected(null);
      },
      onError: (error) => toast.error(error.message),
    });
  };

  return (
    <PageBody className="max-w-[1400px] space-y-6">
      <PageHeader
        title="Authorization model"
        subtitle={
          latest.data
            ? `Version ${latest.data.version} · saved ${timeAgo(latest.data.created_at)}`
            : noModel
              ? "No model yet. Start from the template below."
              : "Loading…"
        }
        actions={
          <>
            <Button
              variant="secondary"
              disabled={!result?.formatted || result.formatted === source}
              onClick={() => result?.formatted && setDraft(result.formatted)}
            >
              <Sparkles strokeWidth={1.75} /> Format
            </Button>
            <Button onClick={save} disabled={!canSave}>
              {write.isPending ? <Loader2 className="motion-safe:animate-spin" /> : null}
              Save as v{nextVersion}
            </Button>
          </>
        }
      />
      {latest.error && !noModel ? <ErrorNotice error={latest.error} /> : null}
      <div className="grid gap-6 xl:grid-cols-[1fr_300px]">
        <Tabs defaultValue="editor" className="min-w-0 gap-4">
          <div className="flex items-center justify-between gap-3">
            <TabsList aria-label="Model view">
              <TabsTrigger value="editor">Editor</TabsTrigger>
              <TabsTrigger value="graph">Graph</TabsTrigger>
            </TabsList>
            <p className="flex items-center gap-1.5 text-[13px] text-muted-foreground" aria-live="polite">
              {pending ? (
                <Loader2 className="size-3.5 motion-safe:animate-spin" />
              ) : validationError ? (
                <AlertTriangle className="size-3.5 text-warning" strokeWidth={2} />
              ) : result?.valid ? (
                <CheckCircle2 className="size-3.5 text-success" strokeWidth={2} />
              ) : (
                <AlertTriangle className="size-3.5 text-destructive" strokeWidth={2} />
              )}
              {pending
                ? "Checking…"
                : validationError
                  ? `Couldn't validate: ${validationError.message}`
                  : result?.valid
                    ? [dirty ? "Valid, unsaved changes" : "Valid", warningCount ? plural(warningCount, "warning") : null]
                        .filter(Boolean)
                        .join(" · ")
                    : plural(errorCount, "problem")}
            </p>
          </div>
          <TabsContent value="editor" className="space-y-4">
            <div className="h-[calc(100dvh-300px)] min-h-[420px] overflow-hidden rounded-xl border border-border/60 bg-card shadow-xs">
              <DslEditor
                value={source}
                onChange={setDraft}
                issues={issues}
                onSave={save}
                onReady={(handle) => {
                  editor.current = handle;
                }}
              />
            </div>
            <Problems issues={issues} onSelect={(issue) => editor.current?.reveal(issue.line, issue.column)} />
          </TabsContent>
          <TabsContent value="graph">
            {result?.ast ? (
              <ModelGraph ast={result.ast} />
            ) : (
              <p className="text-[13px] text-muted-foreground">Fix the problems in the editor to see the graph.</p>
            )}
          </TabsContent>
        </Tabs>
        <aside className="space-y-6">
          <section className="space-y-2">
            <SectionLabel>Versions</SectionLabel>
            <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border/60 bg-card">
              {versions.data?.items.map((version) => {
                const active = selected ? selected === version.id : version.id === latest.data?.id;
                return (
                  <li key={version.id}>
                    <button
                      type="button"
                      onClick={() => {
                        setDraft(null);
                        setSelected(version.id === latest.data?.id ? null : version.id);
                      }}
                      className={cn(
                        "flex min-h-11 w-full items-center gap-3 px-4 text-left text-[13px] transition-colors hover:bg-accent/50 focus-visible:ring-4 focus-visible:ring-ring focus-visible:outline-none focus-visible:ring-inset",
                        active && "bg-primary/10",
                      )}
                    >
                      <span className="font-medium tabular-nums">v{version.version}</span>
                      <span className="flex-1 truncate text-muted-foreground">{timeAgo(version.created_at)}</span>
                      {version.id === latest.data?.id ? <Badge variant="info">Current</Badge> : null}
                    </button>
                  </li>
                );
              })}
              {versions.data?.items.length === 0 ? (
                <li className="px-4 py-3 text-[13px] text-muted-foreground">No versions yet.</li>
              ) : null}
            </ul>
            {selected ? (
              <p className="text-[12px] text-muted-foreground">
                Viewing an older version. Saving creates v{nextVersion} with this content.
              </p>
            ) : null}
          </section>
          <section className="space-y-2">
            <SectionLabel>Syntax</SectionLabel>
            <dl className="divide-y divide-border rounded-xl border border-border/60 bg-card text-[13px]">
              {CHEAT_SHEET.map(([code, meaning]) => (
                <div key={code} className="space-y-0.5 px-4 py-2.5">
                  <dt className="font-mono text-[12px]">{code}</dt>
                  <dd className="text-muted-foreground">{meaning}</dd>
                </div>
              ))}
            </dl>
          </section>
        </aside>
      </div>
    </PageBody>
  );
}
