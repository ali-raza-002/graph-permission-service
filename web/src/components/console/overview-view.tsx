"use client";

import { ArrowRight, Braces, FlaskConical } from "lucide-react";
import Link from "next/link";
import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from "recharts";
import { DecisionBadge } from "@/components/console/decision-badge";
import { ErrorNotice, PageBody, PageHeader, SectionLabel } from "@/components/console/page";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import { Skeleton } from "@/components/ui/skeleton";
import { useDecisions, useOverview } from "@/lib/api/hooks";
import type { StoreOverview } from "@/lib/api/schemas";
import { formatClock, formatMs, formatNumber, formatPercent, timeAgo } from "@/lib/format";

const chartConfig = {
  allowed: { label: "Allowed", color: "var(--chart-5)" },
  denied: { label: "Denied", color: "var(--chart-4)" },
} satisfies ChartConfig;

function Kpi({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <Card className="gap-1 py-4">
      <CardContent className="space-y-1 px-4 sm:px-5">
        <p className="text-[13px] text-muted-foreground">{label}</p>
        <p className="text-[22px] leading-[28px] font-semibold tracking-tight tabular-nums sm:text-[28px] sm:leading-[34px]">{value}</p>
        <p className="text-[12px] text-muted-foreground">{detail}</p>
      </CardContent>
    </Card>
  );
}

function Timeline({ data }: { data: StoreOverview["decisions"]["timeline"] }) {
  const points = data.map((p) => ({ ...p, label: formatClock(p.bucket) }));
  return (
    <ChartContainer config={chartConfig} className="aspect-auto h-64 w-full">
      <AreaChart data={points} margin={{ left: 0, right: 8, top: 8 }}>
        <defs>
          {(["allowed", "denied"] as const).map((key) => (
            <linearGradient key={key} id={`fill-${key}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={`var(--color-${key})`} stopOpacity={0.2} />
              <stop offset="100%" stopColor={`var(--color-${key})`} stopOpacity={0} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid vertical={false} strokeDasharray="3 3" className="stroke-border" />
        <XAxis dataKey="label" tickLine={false} axisLine={false} tickMargin={8} fontSize={11} minTickGap={24} />
        <YAxis tickLine={false} axisLine={false} width={32} fontSize={11} allowDecimals={false} />
        <ChartTooltip content={<ChartTooltipContent indicator="dot" />} />
        <Area
          dataKey="allowed"
          type="monotone"
          stackId="a"
          stroke="var(--color-allowed)"
          strokeWidth={2}
          fill="url(#fill-allowed)"
        />
        <Area
          dataKey="denied"
          type="monotone"
          stackId="a"
          stroke="var(--color-denied)"
          strokeWidth={2}
          fill="url(#fill-denied)"
        />
        <ChartLegend content={<ChartLegendContent />} />
      </AreaChart>
    </ChartContainer>
  );
}

function TuplesByType({ counts }: { counts: Record<string, number> }) {
  const entries = Object.entries(counts);
  const max = Math.max(1, ...entries.map(([, n]) => n));
  if (entries.length === 0) {
    return <p className="text-[13px] text-muted-foreground">No tuples written yet.</p>;
  }
  return (
    <ul className="space-y-3">
      {entries.map(([type, count]) => (
        <li key={type} className="space-y-1.5">
          <div className="flex items-baseline justify-between text-[13px]">
            <span className="font-mono">{type}</span>
            <span className="text-muted-foreground tabular-nums">{formatNumber(count)}</span>
          </div>
          <div className="h-1.5 rounded-full bg-secondary">
            <div className="h-1.5 rounded-full bg-chart-1" style={{ width: `${(count / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

function RecentDecisions({ storeId }: { storeId: string }) {
  const decisions = useDecisions(storeId, {});
  const items = decisions.data?.pages[0]?.items.slice(0, 8) ?? [];
  return (
    <Card className="gap-0 pb-0">
      <CardHeader className="pb-3">
        <CardTitle>Recent decisions</CardTitle>
        <CardDescription>Every check is logged with the trace that produced it.</CardDescription>
        <CardAction>
          <Button asChild variant="ghost" size="sm">
            <Link href={`/stores/${storeId}/decisions`}>
              View all <ArrowRight strokeWidth={1.75} />
            </Link>
          </Button>
        </CardAction>
      </CardHeader>
      <ul className="divide-y divide-border border-t border-border/60">
        {decisions.isPending
          ? Array.from({ length: 4 }, (_, i) => (
              <li key={i} className="px-5 py-3">
                <Skeleton className="h-4 w-2/3" />
              </li>
            ))
          : null}
        {items.map((d) => (
          <li key={d.id}>
            <Link
              href={`/stores/${storeId}/decisions?id=${d.id}`}
              className="flex min-h-11 items-center gap-3 px-5 py-2 text-[13px] transition-colors hover:bg-accent/50"
            >
              <DecisionBadge allowed={d.allowed} count={d.result_count} />
              <span className="min-w-0 flex-1 truncate font-mono">
                {d.subject} <span className="text-muted-foreground">→</span> {d.relation}{" "}
                <span className="text-muted-foreground">on</span> {d.object}
              </span>
              <span className="hidden text-muted-foreground tabular-nums sm:inline">{formatMs(d.duration_ms)}</span>
              <span className="w-24 text-right text-[12px] text-muted-foreground">{timeAgo(d.created_at)}</span>
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function OverviewView({ storeId }: { storeId: string }) {
  const overview = useOverview(storeId);
  const data = overview.data;

  return (
    <PageBody>
      <PageHeader
        title={data?.store.name ?? "Overview"}
        subtitle={
          data ? (
            <>
              Revision <span className="tabular-nums">{formatNumber(data.store.revision)}</span>
              {data.latest_model ? ` · model v${data.latest_model.version}` : " · no model yet"} · last{" "}
              {data.decisions.window_hours} hours
            </>
          ) : (
            "Loading…"
          )
        }
        actions={
          <>
            <Button asChild variant="secondary">
              <Link href={`/stores/${storeId}/model`}>
                <Braces strokeWidth={1.75} /> Edit model
              </Link>
            </Button>
            <Button asChild>
              <Link href={`/stores/${storeId}/playground`}>
                <FlaskConical strokeWidth={1.75} /> Open playground
              </Link>
            </Button>
          </>
        }
      />
      {overview.error ? <ErrorNotice error={overview.error} /> : null}
      <section className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4" aria-label="Key metrics">
        {data ? (
          <>
            <Kpi
              label="Checks"
              value={formatNumber(data.decisions.total)}
              detail={`${formatNumber(data.decisions.allowed)} allowed · ${formatNumber(data.decisions.denied)} denied · ${formatNumber(data.decisions.list_queries)} list ${data.decisions.list_queries === 1 ? "query" : "queries"}`}
            />
            <Kpi
              label="Allow rate"
              value={formatPercent(data.decisions.allow_rate)}
              detail={`${formatPercent(data.decisions.cached_rate)} answered from cache`}
            />
            <Kpi
              label="p95 latency"
              value={formatMs(data.decisions.p95_ms)}
              detail={`p50 ${formatMs(data.decisions.p50_ms)}`}
            />
            <Kpi
              label="Tuples"
              value={formatNumber(data.tuple_count)}
              detail={`${data.model_count} model version${data.model_count === 1 ? "" : "s"}`}
            />
          </>
        ) : (
          Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-[118px] rounded-xl" />)
        )}
      </section>
      <section className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Decisions per hour</CardTitle>
            <CardDescription>Allowed and denied checks over the last day.</CardDescription>
          </CardHeader>
          <CardContent>
            {data ? <Timeline data={data.decisions.timeline} /> : <Skeleton className="h-64 w-full" />}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Tuples by type</CardTitle>
            <CardDescription>Live relationships at the current revision.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {data ? <TuplesByType counts={data.tuples_by_type} /> : <Skeleton className="h-40 w-full" />}
            {data ? (
              <div className="space-y-2">
                <SectionLabel>Check cache</SectionLabel>
                <p className="text-[13px] text-muted-foreground">
                  {data.cache.backend} backend ·{" "}
                  <span className="text-foreground tabular-nums">{formatPercent(data.cache.hit_rate)}</span> hit rate
                  across all stores since this API process started
                </p>
              </div>
            ) : null}
          </CardContent>
        </Card>
      </section>
      <RecentDecisions storeId={storeId} />
    </PageBody>
  );
}
