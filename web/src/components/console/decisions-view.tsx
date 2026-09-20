"use client";

import { ScrollText, Search } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { DecisionBadge } from "@/components/console/decision-badge";
import { EmptyState, ErrorNotice, PageBody, PageHeader, SectionLabel } from "@/components/console/page";
import { TraceView } from "@/components/graph/trace-view";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useDecision, useDecisions } from "@/lib/api/hooks";
import type { DecisionFilter } from "@/lib/api/warden";
import { formatMs, timeAgo } from "@/lib/format";

type Verdict = "all" | "allowed" | "denied";

function DecisionSheet({ storeId, decisionId, onClose }: { storeId: string; decisionId: string | null; onClose: () => void }) {
  const decision = useDecision(storeId, decisionId);
  const d = decision.data;
  return (
    <Sheet open={decisionId !== null} onOpenChange={(open) => (open ? null : onClose())}>
      <SheetContent className="w-full gap-0 overflow-y-auto sm:max-w-3xl">
        <SheetHeader className="border-b border-border/60 px-6 py-5">
          <SheetTitle className="flex items-center gap-3 text-[17px]">
            Decision
            {d ? <DecisionBadge allowed={d.allowed} count={d.result_count} /> : null}
          </SheetTitle>
          <SheetDescription className="font-mono text-[12px]">{decisionId}</SheetDescription>
        </SheetHeader>
        <div className="space-y-6 px-6 py-6">
          {decision.error ? <ErrorNotice error={decision.error} /> : null}
          {!d ? <Skeleton className="h-64 w-full rounded-xl" /> : null}
          {d ? (
            <>
              <dl className="divide-y divide-border rounded-xl border border-border/60 bg-card text-[13px]">
                {[
                  ["Subject", d.subject],
                  ["Relation", d.relation],
                  ["Object", d.object],
                  ["Revision", String(d.revision)],
                  ["Model", d.model_id],
                  ["Latency", `${formatMs(d.duration_ms)}${d.cached ? " · cached" : ""}`],
                  ["Contextual tuples", String(d.contextual_tuples)],
                  ["When", new Date(d.created_at).toLocaleString()],
                ].map(([label, value]) => (
                  <div key={label} className="flex min-h-10 items-center justify-between gap-4 px-4">
                    <dt className="text-muted-foreground">{label}</dt>
                    <dd className="truncate text-right font-mono text-[12.5px]">{value}</dd>
                  </div>
                ))}
              </dl>
              {d.trace ? (
                <div className="space-y-2">
                  <SectionLabel>Why</SectionLabel>
                  <TraceView trace={d.trace} className="h-[460px]" />
                </div>
              ) : (
                <p className="text-[13px] text-muted-foreground">
                  List queries record the result count rather than a single trace.
                </p>
              )}
              {d.kind === "check" ? (
                <Button asChild variant="secondary">
                  <Link
                    href={`/stores/${storeId}/playground?object=${encodeURIComponent(d.object)}&relation=${encodeURIComponent(d.relation)}&user=${encodeURIComponent(d.subject)}`}
                  >
                    Re-run in playground
                  </Link>
                </Button>
              ) : null}
            </>
          ) : null}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function Decisions({ storeId }: { storeId: string }) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [verdict, setVerdict] = useState<Verdict>("all");
  const [search, setSearch] = useState("");
  const [subject, setSubject] = useState("");
  const filter: DecisionFilter = {
    ...(verdict === "all" ? {} : { allowed: verdict === "allowed" }),
    ...(subject ? { subject } : {}),
  };
  const decisions = useDecisions(storeId, filter);
  const rows = decisions.data?.pages.flatMap((p) => p.items) ?? [];
  const openId = params.get("id");
  const open = (id: string | null) => router.replace(id ? `${pathname}?id=${id}` : pathname, { scroll: false });

  return (
    <PageBody className="space-y-6">
      <PageHeader title="Decisions" subtitle="Every check and list query, with the trace that explains it." />
      <div className="flex flex-wrap items-center gap-3">
        <Tabs value={verdict} onValueChange={(v) => setVerdict(v === "allowed" || v === "denied" ? v : "all")}>
          <TabsList aria-label="Filter by result">
            <TabsTrigger value="all">All</TabsTrigger>
            <TabsTrigger value="allowed">Allowed</TabsTrigger>
            <TabsTrigger value="denied">Denied</TabsTrigger>
          </TabsList>
        </Tabs>
        <form
          role="search"
          className="relative"
          onSubmit={(e) => {
            e.preventDefault();
            setSubject(search.trim());
          }}
        >
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" strokeWidth={1.75} />
          <Input
            aria-label="Filter by subject"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              if (!e.target.value) setSubject("");
            }}
            placeholder="Subject, e.g. user:dev"
            className="w-64 rounded-full border-transparent bg-secondary pl-9 font-mono"
          />
        </form>
      </div>
      {decisions.error ? <ErrorNotice error={decisions.error} /> : null}
      <div className="overflow-hidden rounded-xl border border-border/60 bg-card shadow-xs">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="h-10 w-28 pl-4 text-[12px]">Result</TableHead>
              <TableHead className="h-10 text-[12px] sm:hidden">Query</TableHead>
              <TableHead className="hidden h-10 text-[12px] sm:table-cell">Subject</TableHead>
              <TableHead className="hidden h-10 text-[12px] sm:table-cell">Relation</TableHead>
              <TableHead className="hidden h-10 text-[12px] sm:table-cell">Object</TableHead>
              <TableHead className="hidden h-10 text-right text-[12px] sm:table-cell">Latency</TableHead>
              <TableHead className="hidden h-10 text-right text-[12px] md:table-cell">Revision</TableHead>
              <TableHead className="hidden h-10 pr-4 text-right text-[12px] sm:table-cell">When</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {decisions.isPending
              ? Array.from({ length: 8 }, (_, i) => (
                  <TableRow key={i}>
                    <TableCell colSpan={8} className="pl-4">
                      <Skeleton className="h-4 w-full" />
                    </TableCell>
                  </TableRow>
                ))
              : null}
            {rows.map((d) => (
              <TableRow
                key={d.id}
                tabIndex={0}
                onClick={() => open(d.id)}
                onKeyDown={(e) => (e.key === "Enter" ? open(d.id) : null)}
                className="h-11 cursor-pointer hover:bg-accent/50 focus-visible:bg-accent/50 focus-visible:ring-4 focus-visible:ring-ring focus-visible:outline-none focus-visible:ring-inset data-[selected=true]:bg-primary/10"
                data-selected={openId === d.id}
                aria-label={`${verdictLabel(d.allowed, d.result_count)}: ${d.subject} ${d.relation} ${d.object}`}
              >
                <TableCell className="pl-4">
                  <DecisionBadge allowed={d.allowed} count={d.result_count} />
                </TableCell>
                <TableCell className="py-2 font-mono text-[12.5px] whitespace-normal sm:hidden">
                  <span className="block">
                    {d.subject} <span className="text-muted-foreground">→</span> {d.relation}
                  </span>
                  <span className="block break-all text-muted-foreground">{d.object}</span>
                </TableCell>
                <TableCell className="hidden font-mono text-[12.5px] sm:table-cell">{d.subject}</TableCell>
                <TableCell className="hidden font-mono text-[12.5px] sm:table-cell">{d.relation}</TableCell>
                <TableCell className="hidden max-w-64 truncate font-mono text-[12.5px] sm:table-cell">{d.object}</TableCell>
                <TableCell className="hidden text-right text-[13px] tabular-nums sm:table-cell">
                  {formatMs(d.duration_ms)}
                  {d.cached ? <span className="ml-1 text-muted-foreground">·c</span> : null}
                </TableCell>
                <TableCell className="hidden text-right text-[13px] tabular-nums md:table-cell">{d.revision}</TableCell>
                <TableCell className="hidden pr-4 text-right text-[12px] text-muted-foreground sm:table-cell">{timeAgo(d.created_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {!decisions.isPending && rows.length === 0 ? (
          <EmptyState icon={ScrollText} title="No decisions yet" description="Run a check from the playground or the SDK and it will appear here." />
        ) : null}
        {decisions.hasNextPage ? (
          <div className="border-t border-border/60 p-3 text-center">
            <Button variant="ghost" size="sm" onClick={() => decisions.fetchNextPage()} disabled={decisions.isFetchingNextPage}>
              Load more
            </Button>
          </div>
        ) : null}
      </div>
      <DecisionSheet storeId={storeId} decisionId={openId} onClose={() => open(null)} />
    </PageBody>
  );
}

function verdictLabel(allowed: boolean | null, count: number | null | undefined): string {
  if (allowed === null) return `${count ?? 0} found`;
  return allowed ? "Allowed" : "Denied";
}

export function DecisionsView({ storeId }: { storeId: string }) {
  return (
    <Suspense>
      <Decisions storeId={storeId} />
    </Suspense>
  );
}
