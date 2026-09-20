"use client";

import { History, Minus, Plus, Rows3, Search, Trash2, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { EmptyState, ErrorNotice, PageBody, PageHeader } from "@/components/console/page";
import { TupleSheet } from "@/components/console/tuple-sheet";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useChanges, useLatestModel, useTuples, useWriteTuples } from "@/lib/api/hooks";
import type { StoredTuple, TupleChange } from "@/lib/api/schemas";
import type { TupleFilter } from "@/lib/api/warden";
import { formatNumber, splitRef, timeAgo } from "@/lib/format";

const ALL = "__all__";

function Ref({ value }: { value: string }) {
  const { type, id, relation } = splitRef(value);
  return (
    <span className="font-mono text-[12.5px]">
      <span className="text-muted-foreground">{type}:</span>
      {id}
      {relation ? <span className="text-muted-foreground">#{relation}</span> : null}
    </span>
  );
}

function DeleteTuple({ storeId, tuple }: { storeId: string; tuple: StoredTuple }) {
  const write = useWriteTuples(storeId);
  return (
    <AlertDialog>
      <Tooltip>
        <TooltipTrigger asChild>
          <AlertDialogTrigger asChild>
            <Button variant="destructive-ghost" size="icon-sm" aria-label="Delete tuple">
              <Trash2 strokeWidth={1.75} />
            </Button>
          </AlertDialogTrigger>
        </TooltipTrigger>
        <TooltipContent>Delete</TooltipContent>
      </Tooltip>
      <AlertDialogContent className="rounded-2xl">
        <AlertDialogHeader>
          <AlertDialogTitle className="text-[17px]">Delete this tuple?</AlertDialogTitle>
          <AlertDialogDescription className="font-mono text-[12.5px] break-all">
            {tuple.object}#{tuple.relation}@{tuple.user}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <p className="text-[13px] text-muted-foreground">
          The tuple stays visible to snapshot reads at earlier revisions.
        </p>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            className="bg-destructive text-white hover:bg-destructive/90"
            onClick={() =>
              write.mutate(
                { deletes: [{ object: tuple.object, relation: tuple.relation, user: tuple.user }] },
                {
                  onSuccess: (r) => toast.success(`Deleted at revision ${r.revision}`),
                  onError: (e) => toast.error(e.message),
                },
              )
            }
          >
            Delete
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function TupleTable({ storeId, filter }: { storeId: string; filter: TupleFilter }) {
  const tuples = useTuples(storeId, filter);
  const rows = tuples.data?.pages.flatMap((p) => p.items) ?? [];
  if (tuples.error) return <ErrorNotice error={tuples.error} />;
  return (
    <div className="overflow-hidden rounded-xl border border-border/60 bg-card shadow-xs">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="h-10 pl-4 text-[12px]">Object</TableHead>
            <TableHead className="h-10 text-[12px]">Relation</TableHead>
            <TableHead className="h-10 text-[12px]">User</TableHead>
            <TableHead className="hidden h-10 text-right text-[12px] sm:table-cell">Revision</TableHead>
            <TableHead className="hidden h-10 text-[12px] md:table-cell">Written</TableHead>
            <TableHead className="h-10 w-12 pr-4">
              <span className="sr-only">Actions</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {tuples.isPending
            ? Array.from({ length: 6 }, (_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={6} className="pl-4">
                    <Skeleton className="h-4 w-full" />
                  </TableCell>
                </TableRow>
              ))
            : null}
          {rows.map((t) => (
            <TableRow key={t.id} className="h-11 hover:bg-accent/50">
              <TableCell className="pl-4 whitespace-normal break-all sm:whitespace-nowrap">
                <Ref value={t.object} />
              </TableCell>
              <TableCell>
                <Badge variant="secondary" className="font-mono">
                  {t.relation}
                </Badge>
              </TableCell>
              <TableCell className="whitespace-normal break-all sm:whitespace-nowrap">
                <Ref value={t.user} />
              </TableCell>
              <TableCell className="hidden text-right text-[13px] tabular-nums sm:table-cell">{t.created_revision}</TableCell>
              <TableCell className="hidden text-[13px] text-muted-foreground md:table-cell">
                {timeAgo(t.created_at)}
              </TableCell>
              <TableCell className="pr-4 text-right">
                <DeleteTuple storeId={storeId} tuple={t} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {!tuples.isPending && rows.length === 0 ? (
        <EmptyState icon={Rows3} title="No matching tuples" description="Try a different filter, or add a relationship." />
      ) : null}
      {tuples.hasNextPage ? (
        <div className="border-t border-border/60 p-3 text-center">
          <Button variant="ghost" size="sm" onClick={() => tuples.fetchNextPage()} disabled={tuples.isFetchingNextPage}>
            Load more
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function ChangeHistory({ storeId }: { storeId: string }) {
  const changes = useChanges(storeId);
  const items = changes.data?.pages.flatMap((p) => p.items) ?? [];
  const groups = new Map<number, TupleChange[]>();
  for (const change of items) {
    groups.set(change.revision, [...(groups.get(change.revision) ?? []), change]);
  }
  if (changes.error) return <ErrorNotice error={changes.error} />;
  return (
    <div className="space-y-4">
      {changes.isPending ? <Skeleton className="h-40 w-full rounded-xl" /> : null}
      {[...groups.entries()].map(([revision, list]) => (
        <section key={revision} className="overflow-hidden rounded-xl border border-border/60 bg-card shadow-xs">
          <header className="flex items-center justify-between border-b border-border/60 px-4 py-2.5">
            <h3 className="text-[13px] font-semibold">Revision {revision}</h3>
            <span className="text-[12px] text-muted-foreground tabular-nums">
              {list.length} change{list.length === 1 ? "" : "s"}
            </span>
          </header>
          <ul className="divide-y divide-border">
            {list.map((change) => (
              <li
                key={`${change.operation}:${change.tuple_key.object}#${change.tuple_key.relation}@${change.tuple_key.user}`}
                className="flex items-center gap-3 px-4 py-2 text-[12.5px]"
              >
                {change.operation === "write" ? (
                  <Plus className="size-3.5 text-success" strokeWidth={2.25} aria-label="Written" />
                ) : (
                  <Minus className="size-3.5 text-destructive" strokeWidth={2.25} aria-label="Deleted" />
                )}
                <span className="truncate font-mono">
                  {change.tuple_key.object}
                  <span className="text-muted-foreground">#{change.tuple_key.relation}@</span>
                  {change.tuple_key.user}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ))}
      {changes.hasNextPage ? (
        <div className="text-center">
          <Button variant="ghost" size="sm" onClick={() => changes.fetchNextPage()}>
            Older changes
          </Button>
        </div>
      ) : null}
    </div>
  );
}

export function TuplesView({ storeId }: { storeId: string }) {
  const model = useLatestModel(storeId);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState<TupleFilter>({});
  const [filter, setFilter] = useState<TupleFilter>({});
  const types = model.data?.ast.types.filter((t) => t.relations.length > 0) ?? [];
  const relations = types.find((t) => t.name === draft.object_type)?.relations ?? [];
  const tuples = useTuples(storeId, filter);
  const revision = tuples.data?.pages[0]?.revision;

  const set = (key: keyof TupleFilter, value: string) => {
    setDraft((current) => {
      const next = { ...current };
      if (value && value !== ALL) next[key] = value;
      else delete next[key];
      if (key === "object_type") delete next.relation;
      return next;
    });
  };
  const apply = (event?: React.FormEvent) => {
    event?.preventDefault();
    setFilter(draft);
  };
  const active = Object.keys(filter).length > 0;

  return (
    <PageBody className="space-y-6">
      <PageHeader
        title="Tuples"
        subtitle={
          revision !== undefined
            ? `Snapshot at revision ${formatNumber(revision)}`
            : "Relationship tuples stored for this store"
        }
        actions={
          <Button onClick={() => setAdding(true)} disabled={!model.data}>
            <Plus strokeWidth={1.75} /> Add tuple
          </Button>
        }
      />
      <Tabs defaultValue="tuples" className="gap-4">
        <TabsList aria-label="Tuple views">
          <TabsTrigger value="tuples">
            <Rows3 strokeWidth={1.75} /> Tuples
          </TabsTrigger>
          <TabsTrigger value="history">
            <History strokeWidth={1.75} /> Change history
          </TabsTrigger>
        </TabsList>
        <TabsContent value="tuples" className="space-y-4">
          <form onSubmit={apply} className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:items-center" role="search">
            <Select value={draft.object_type ?? ALL} onValueChange={(v) => set("object_type", v)}>
              <SelectTrigger className="h-9 w-full rounded-lg sm:w-40" aria-label="Object type">
                <SelectValue placeholder="Any type" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>Any type</SelectItem>
                {types.map((t) => (
                  <SelectItem key={t.name} value={t.name}>
                    {t.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              aria-label="Object id"
              placeholder="Object id"
              value={draft.object_id ?? ""}
              onChange={(e) => set("object_id", e.target.value)}
              className="w-full font-mono sm:w-40"
            />
            <Select
              value={draft.relation ?? ALL}
              onValueChange={(v) => set("relation", v)}
              disabled={!draft.object_type}
            >
              <SelectTrigger className="h-9 w-full rounded-lg sm:w-40" aria-label="Relation">
                <SelectValue placeholder="Any relation" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>Any relation</SelectItem>
                {relations.map((r) => (
                  <SelectItem key={r.name} value={r.name}>
                    {r.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              aria-label="User"
              placeholder="user:anne"
              value={draft.user ?? ""}
              onChange={(e) => set("user", e.target.value)}
              className="w-full font-mono sm:w-48"
            />
            <Button type="submit" variant="secondary">
              <Search strokeWidth={1.75} /> Filter
            </Button>
            {active ? (
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setDraft({});
                  setFilter({});
                }}
              >
                <X strokeWidth={1.75} /> Clear
              </Button>
            ) : null}
          </form>
          <TupleTable storeId={storeId} filter={filter} />
        </TabsContent>
        <TabsContent value="history">
          <ChangeHistory storeId={storeId} />
        </TabsContent>
      </Tabs>
      <TupleSheet storeId={storeId} model={model.data?.ast} open={adding} onOpenChange={setAdding} />
    </PageBody>
  );
}
