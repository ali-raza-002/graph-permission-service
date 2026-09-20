"use client";

import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, FlaskConical, Loader2, Plus, Trash2, XCircle } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { EmptyState, ErrorNotice, PageBody, PageHeader, SectionLabel } from "@/components/console/page";
import { FlowGraph } from "@/components/graph/flow-graph";
import { TraceView } from "@/components/graph/trace-view";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useDecisions, useLatestModel } from "@/lib/api/hooks";
import type { AuthorizationModel, ConsistencyMode, TupleKey } from "@/lib/api/schemas";
import { warden, type CheckInput } from "@/lib/api/warden";
import { formatMs, splitRef } from "@/lib/format";
import { expandToGraph } from "@/lib/graph";

const CONSISTENCY: { value: ConsistencyMode; label: string }[] = [
  { value: "minimize_latency", label: "Minimize latency" },
  { value: "fully_consistent", label: "Fully consistent" },
  { value: "at_least_as_fresh", label: "At least as fresh as token" },
  { value: "at_exact_snapshot", label: "At exact snapshot" },
];

function relationsFor(model: AuthorizationModel | undefined, ref: string): string[] {
  const { type } = splitRef(ref);
  return model?.types.find((t) => t.name === type)?.relations.map((r) => r.name) ?? [];
}

function Field({ id, label, children, hint }: { id: string; label: string; children: React.ReactNode; hint?: string }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="text-[13px]">
        {label}
      </Label>
      {children}
      {hint ? <p className="text-[12px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function RelationSelect({
  id,
  value,
  onChange,
  options,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  options: string[];
}) {
  if (options.length === 0) {
    return (
      <Input id={id} value={value} onChange={(e) => onChange(e.target.value)} placeholder="viewer" className="font-mono" />
    );
  }
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger id={id} className="w-full font-mono">
        <SelectValue placeholder="Choose a relation" />
      </SelectTrigger>
      <SelectContent>
        {options.map((r) => (
          <SelectItem key={r} value={r} className="font-mono">
            {r}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function parseTuple(raw: string): TupleKey | null {
  const match = /^([^#\s]+)#([^@\s]+)@(\S+)$/.exec(raw.trim());
  if (!match) return null;
  const [, object = "", relation = "", user = ""] = match;
  return { object, relation, user };
}

function CheckPanel({ storeId, model }: { storeId: string; model: AuthorizationModel | undefined }) {
  const params = useSearchParams();
  const [object, setObject] = useState(params.get("object") ?? "");
  const [relation, setRelation] = useState(params.get("relation") ?? "");
  const [user, setUser] = useState(params.get("user") ?? "");
  const [contextual, setContextual] = useState<string[]>([]);
  const [mode, setMode] = useState<ConsistencyMode>("minimize_latency");
  const [token, setToken] = useState("");
  const recent = useDecisions(storeId, {}, { poll: false });
  const examples = useMemo(() => {
    const seen = new Set<string>();
    const out: TupleKey[] = [];
    for (const d of recent.data?.pages[0]?.items ?? []) {
      const key = `${d.object}#${d.relation}@${d.subject}`;
      if (d.kind !== "check" || seen.has(key)) continue;
      seen.add(key);
      out.push({ object: d.object, relation: d.relation, user: d.subject });
      if (out.length === 4) break;
    }
    return out;
  }, [recent.data]);

  // The question travels as the mutation variable, so the verdict is always shown next
  // to the query that produced it rather than whatever the form says now.
  const check = useMutation({ mutationFn: (input: CheckInput) => warden.check(storeId, input) });
  const run = () =>
    check.mutate({
      tuple_key: { object: object.trim(), relation, user: user.trim() },
      contextual_tuples: contextual.map(parseTuple).filter((t): t is TupleKey => t !== null),
      consistency: mode === "at_least_as_fresh" || mode === "at_exact_snapshot" ? { mode, token } : { mode },
      explain: true,
    });
  const invalidContext = contextual.some((c) => c.trim() && parseTuple(c) === null);
  const ready = object.includes(":") && relation && user.includes(":") && !invalidContext;
  const result = check.data;
  const asked = check.variables?.tuple_key;

  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[340px_1fr]">
      <form
        className="space-y-5"
        onSubmit={(event) => {
          event.preventDefault();
          if (ready) run();
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" && (event.metaKey || event.ctrlKey) && ready) run();
        }}
      >
        <div className="space-y-4 rounded-xl border border-border/60 bg-card p-5 shadow-xs">
          <Field id="check-object" label="Object">
            <Input
              id="check-object"
              value={object}
              onChange={(e) => setObject(e.target.value)}
              placeholder="document:roadmap"
              className="font-mono"
              autoComplete="off"
            />
          </Field>
          <Field id="check-relation" label="Relation">
            <RelationSelect id="check-relation" value={relation} onChange={setRelation} options={relationsFor(model, object)} />
          </Field>
          <Field id="check-user" label="User">
            <Input
              id="check-user"
              value={user}
              onChange={(e) => setUser(e.target.value)}
              placeholder="user:anne"
              className="font-mono"
              autoComplete="off"
            />
          </Field>
        </div>
        <div className="space-y-3 rounded-xl border border-border/60 bg-card p-5 shadow-xs">
          <div className="flex items-center justify-between">
            <SectionLabel>Contextual tuples</SectionLabel>
            <Button type="button" variant="ghost" size="icon-sm" aria-label="Add contextual tuple" onClick={() => setContextual((c) => [...c, ""])}>
              <Plus strokeWidth={1.75} />
            </Button>
          </div>
          {contextual.length === 0 ? (
            <p className="text-[12px] text-muted-foreground">
              Facts that hold only for this request, such as an IP-based group from the session.
            </p>
          ) : null}
          {contextual.map((value, index) => (
            <div key={index} className="flex items-center gap-2">
              <Input
                aria-label={`Contextual tuple ${index + 1}`}
                value={value}
                onChange={(e) => setContextual((c) => c.map((v, i) => (i === index ? e.target.value : v)))}
                placeholder="team:eng#member@user:zoe"
                aria-invalid={value.trim() !== "" && parseTuple(value) === null}
                className="font-mono text-[12.5px]"
              />
              <Button
                type="button"
                variant="destructive-ghost"
                size="icon-sm"
                aria-label="Remove contextual tuple"
                onClick={() => setContextual((c) => c.filter((_, i) => i !== index))}
              >
                <Trash2 strokeWidth={1.75} />
              </Button>
            </div>
          ))}
          <Field id="check-consistency" label="Consistency">
            <Select
              value={mode}
              onValueChange={(v) => {
                const next = CONSISTENCY.find((c) => c.value === v);
                if (next) setMode(next.value);
              }}
            >
              <SelectTrigger id="check-consistency" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CONSISTENCY.map((c) => (
                  <SelectItem key={c.value} value={c.value}>
                    {c.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          {mode === "at_least_as_fresh" || mode === "at_exact_snapshot" ? (
            <Field id="check-token" label="Consistency token" hint="Returned by every write as consistency_token.">
              <Input id="check-token" value={token} onChange={(e) => setToken(e.target.value)} placeholder="zk1…" className="font-mono" />
            </Field>
          ) : null}
        </div>
        <Button type="submit" className="w-full" disabled={!ready || check.isPending}>
          {check.isPending ? <Loader2 className="motion-safe:animate-spin" /> : null}
          Check permission
          <kbd className="ml-1 rounded bg-primary-foreground/15 px-1.5 font-mono text-[11px]">⌘↵</kbd>
        </Button>
        {examples.length > 0 ? (
          <div className="space-y-2">
            <SectionLabel>Recently checked</SectionLabel>
            <div className="flex flex-col gap-1.5">
              {examples.map((ex) => (
                <button
                  key={`${ex.object}#${ex.relation}@${ex.user}`}
                  type="button"
                  onClick={() => {
                    setObject(ex.object);
                    setRelation(ex.relation);
                    setUser(ex.user);
                  }}
                  className="truncate rounded-lg px-2 py-1.5 text-left font-mono text-[12px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                >
                  {ex.user} · {ex.relation} · {ex.object}
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </form>
      <section aria-live="polite" className="min-w-0 space-y-4">
        {check.error ? <ErrorNotice error={check.error} /> : null}
        {result && asked ? (
          <>
            <div className="flex flex-wrap items-center gap-4 rounded-xl border border-border/60 bg-card px-5 py-4 shadow-xs">
              {result.allowed ? (
                <CheckCircle2 className="size-9 text-success" strokeWidth={1.75} />
              ) : (
                <XCircle className="size-9 text-destructive" strokeWidth={1.75} />
              )}
              <div className="min-w-48 flex-1">
                <p className="text-[22px] leading-7 font-semibold">{result.allowed ? "Allowed" : "Denied"}</p>
                <p className="truncate font-mono text-[12.5px] text-muted-foreground">
                  {asked.user} → {asked.relation} on {asked.object}
                </p>
              </div>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-[12px] sm:grid-cols-4">
                {[
                  ["Latency", formatMs(result.duration_ms)],
                  ["Revision", String(result.revision)],
                  ["Sub-problems", String(result.stats.dispatches)],
                  ["Queries", String(result.stats.queries)],
                ].map(([label, value]) => (
                  <div key={label}>
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd className="font-medium tabular-nums">{value}</dd>
                  </div>
                ))}
              </dl>
            </div>
            <TraceView trace={result.trace} className="h-[calc(100dvh-380px)] min-h-[440px]" />
            <p className="text-[12px] text-muted-foreground">
              Logged as{" "}
              <Link href={`/stores/${storeId}/decisions?id=${result.decision_id}`} className="font-mono text-primary hover:underline">
                {result.decision_id}
              </Link>{" "}
              · token <span className="font-mono">{result.consistency_token}</span>
            </p>
          </>
        ) : (
          <div className="rounded-xl border border-dashed border-border bg-card/50">
            <EmptyState
              icon={FlaskConical}
              title="Ask a question"
              description="Run a check to see the decision and the exact path through your model that produced it."
            />
          </div>
        )}
      </section>
    </div>
  );
}

function ExpandPanel({ storeId, model }: { storeId: string; model: AuthorizationModel | undefined }) {
  const [object, setObject] = useState("");
  const [relation, setRelation] = useState("");
  const expand = useMutation({ mutationFn: () => warden.expand(storeId, { object: object.trim(), relation }) });
  const graph = useMemo(() => (expand.data ? expandToGraph(expand.data.tree) : null), [expand.data]);
  return (
    <div className="space-y-4">
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          expand.mutate();
        }}
      >
        <div className="w-64">
          <Field id="expand-object" label="Object">
            <Input id="expand-object" value={object} onChange={(e) => setObject(e.target.value)} placeholder="document:roadmap" className="font-mono" />
          </Field>
        </div>
        <div className="w-48">
          <Field id="expand-relation" label="Relation">
            <RelationSelect id="expand-relation" value={relation} onChange={setRelation} options={relationsFor(model, object)} />
          </Field>
        </div>
        <Button type="submit" disabled={!object.includes(":") || !relation || expand.isPending}>
          {expand.isPending ? <Loader2 className="motion-safe:animate-spin" /> : null}
          Expand
        </Button>
      </form>
      {expand.error ? <ErrorNotice error={expand.error} /> : null}
      {graph ? (
        <div className="overflow-hidden rounded-xl border border-border/60 bg-background">
          <FlowGraph graph={graph} className="h-[calc(100dvh-320px)] min-h-[440px]" ariaLabel={`Userset expansion of ${object}#${relation}`} />
        </div>
      ) : null}
    </div>
  );
}

function ResultList({ items, empty }: { items: string[]; empty: string }) {
  if (items.length === 0) return <p className="text-[13px] text-muted-foreground">{empty}</p>;
  return (
    <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border/60 bg-card shadow-xs">
      {items.map((item) => (
        <li key={item} className="flex min-h-11 items-center px-4 font-mono text-[12.5px]">
          {item}
        </li>
      ))}
    </ul>
  );
}

function ListObjectsPanel({ storeId, model }: { storeId: string; model: AuthorizationModel | undefined }) {
  const types = model?.types.filter((t) => t.relations.length > 0).map((t) => t.name) ?? [];
  const [type, setType] = useState("");
  const [relation, setRelation] = useState("");
  const [user, setUser] = useState("");
  const list = useMutation({
    mutationFn: () => warden.listObjects(storeId, { object_type: type, relation, user: user.trim(), contextual_tuples: [] }),
  });
  return (
    <div className="space-y-4">
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          list.mutate();
        }}
      >
        <div className="w-44">
          <Field id="lo-type" label="Object type">
            <RelationSelect id="lo-type" value={type} onChange={(v) => { setType(v); setRelation(""); }} options={types} />
          </Field>
        </div>
        <div className="w-44">
          <Field id="lo-relation" label="Relation">
            <RelationSelect id="lo-relation" value={relation} onChange={setRelation} options={relationsFor(model, `${type}:x`)} />
          </Field>
        </div>
        <div className="w-56">
          <Field id="lo-user" label="User">
            <Input id="lo-user" value={user} onChange={(e) => setUser(e.target.value)} placeholder="user:anne" className="font-mono" />
          </Field>
        </div>
        <Button type="submit" disabled={!type || !relation || !user.includes(":") || list.isPending}>
          {list.isPending ? <Loader2 className="motion-safe:animate-spin" /> : null}
          List objects
        </Button>
      </form>
      {list.error ? <ErrorNotice error={list.error} /> : null}
      {list.data ? (
        <div className="space-y-2">
          <p className="text-[13px] text-muted-foreground">
            <Badge variant="info">{list.data.objects.length}</Badge> found by reverse expansion in {formatMs(list.data.duration_ms)}
            {list.data.truncated ? " · more may exist beyond the result limit" : ""}
          </p>
          <ResultList items={list.data.objects} empty="No objects grant this relation." />
        </div>
      ) : null}
    </div>
  );
}

function ListUsersPanel({ storeId, model }: { storeId: string; model: AuthorizationModel | undefined }) {
  const [object, setObject] = useState("");
  const [relation, setRelation] = useState("");
  const [userType, setUserType] = useState("user");
  const list = useMutation({
    mutationFn: () => warden.listUsers(storeId, { object: object.trim(), relation, user_type: userType.trim() }),
  });
  return (
    <div className="space-y-4">
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          list.mutate();
        }}
      >
        <div className="w-64">
          <Field id="lu-object" label="Object">
            <Input id="lu-object" value={object} onChange={(e) => setObject(e.target.value)} placeholder="document:roadmap" className="font-mono" />
          </Field>
        </div>
        <div className="w-44">
          <Field id="lu-relation" label="Relation">
            <RelationSelect id="lu-relation" value={relation} onChange={setRelation} options={relationsFor(model, object)} />
          </Field>
        </div>
        <div className="w-44">
          <Field id="lu-type" label="User type">
            <Input id="lu-type" value={userType} onChange={(e) => setUserType(e.target.value)} placeholder="user or team#member" className="font-mono" />
          </Field>
        </div>
        <Button type="submit" disabled={!object.includes(":") || !relation || !userType || list.isPending}>
          {list.isPending ? <Loader2 className="motion-safe:animate-spin" /> : null}
          List users
        </Button>
      </form>
      {list.error ? <ErrorNotice error={list.error} /> : null}
      {list.data ? (
        <div className="space-y-2">
          <p className="text-[13px] text-muted-foreground">
            <Badge variant="info">{list.data.users.length}</Badge> subjects in {formatMs(list.data.duration_ms)}
            {list.data.truncated ? " · more may exist beyond the result limit" : ""}
          </p>
          <ResultList items={list.data.users} empty="Nobody holds this relation." />
        </div>
      ) : null}
    </div>
  );
}

function Playground({ storeId }: { storeId: string }) {
  const model = useLatestModel(storeId);
  const ast = model.data?.ast;
  return (
    <PageBody className="max-w-[1400px] space-y-6">
      <PageHeader
        title="Playground"
        subtitle={model.data ? `Querying model v${model.data.version}` : "Ask Warden questions and see why it answered"}
      />
      <Tabs defaultValue="check" className="gap-5">
        <TabsList aria-label="Query type">
          <TabsTrigger value="check">Check</TabsTrigger>
          <TabsTrigger value="expand">Expand</TabsTrigger>
          <TabsTrigger value="objects">List objects</TabsTrigger>
          <TabsTrigger value="users">List users</TabsTrigger>
        </TabsList>
        <TabsContent value="check">
          <CheckPanel storeId={storeId} model={ast} />
        </TabsContent>
        <TabsContent value="expand">
          <ExpandPanel storeId={storeId} model={ast} />
        </TabsContent>
        <TabsContent value="objects">
          <ListObjectsPanel storeId={storeId} model={ast} />
        </TabsContent>
        <TabsContent value="users">
          <ListUsersPanel storeId={storeId} model={ast} />
        </TabsContent>
      </Tabs>
    </PageBody>
  );
}

export function PlaygroundView({ storeId }: { storeId: string }) {
  return (
    <Suspense>
      <Playground storeId={storeId} />
    </Suspense>
  );
}
