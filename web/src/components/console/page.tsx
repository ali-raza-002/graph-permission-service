import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0 space-y-1">
        <h1 className="text-[28px] leading-[34px] font-semibold tracking-tight">{title}</h1>
        {subtitle ? <p className="text-[13px] leading-[18px] text-muted-foreground">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function PageBody({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("mx-auto w-full max-w-7xl space-y-8 px-4 py-8 sm:px-6 lg:px-8", className)}>{children}</div>;
}

export function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{children}</h2>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: React.ComponentType<{ className?: string; strokeWidth?: number }>;
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      <Icon className="size-10 text-muted-foreground/60" strokeWidth={1.5} />
      <div className="space-y-1">
        <p className="text-[17px] leading-[22px] font-semibold">{title}</p>
        <p className="mx-auto max-w-sm text-[13px] leading-[18px] text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  );
}

export function ErrorNotice({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="flex items-center justify-between gap-3 rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-[13px] text-destructive"
    >
      <span>{error.message}</span>
      {onRetry ? (
        <Button size="sm" variant="outline" className="shrink-0" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}
