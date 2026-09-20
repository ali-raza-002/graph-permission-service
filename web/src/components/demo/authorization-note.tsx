import { ChevronRight, ShieldCheck, ShieldX } from "lucide-react";
import Link from "next/link";
import type { Authorization } from "@/lib/api/workspaces";
import { WORKSPACES_STORE_ID } from "@/lib/api/workspaces";
import { formatMs } from "@/lib/format";
import { cn } from "@/lib/utils";

export function decisionHref(decisionId: string): string {
  return `/stores/${WORKSPACES_STORE_ID}/decisions?id=${encodeURIComponent(decisionId)}`;
}

export function AuthorizationNote({
  authorization,
  relation,
  className,
}: {
  authorization: Authorization;
  relation: string;
  className?: string;
}) {
  return (
    <Link
      href={decisionHref(authorization.decision_id)}
      className={cn(
        "group flex items-center gap-2 rounded-lg px-2 py-1.5 text-[12px] text-muted-foreground transition-colors duration-150 hover:bg-accent/60 focus-visible:ring-4 focus-visible:ring-ring focus-visible:outline-none",
        className,
      )}
    >
      <ShieldCheck className="size-4 shrink-0 text-success" strokeWidth={1.75} />
      <span className="min-w-0 truncate">
        Allowed <span className="font-mono text-foreground">{relation}</span>
        <span className="tabular-nums">
          {" "}
          · rev {authorization.revision} · {formatMs(authorization.duration_ms)}
        </span>
      </span>
      <span className="ml-auto flex shrink-0 items-center text-primary opacity-80 group-hover:opacity-100">
        Trace
        <ChevronRight className="size-3.5" strokeWidth={2} />
      </span>
    </Link>
  );
}

export function DeniedState({
  title,
  description,
  decisionId,
}: {
  title: string;
  description: string;
  decisionId: string | null;
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 py-16 text-center" role="alert">
      <ShieldX className="size-11 text-muted-foreground/60" strokeWidth={1.5} />
      <div className="space-y-1">
        <p className="text-[17px] leading-[22px] font-semibold">{title}</p>
        <p className="mx-auto max-w-sm text-[13px] leading-[18px] text-muted-foreground">{description}</p>
      </div>
      {decisionId ? (
        <Link
          href={decisionHref(decisionId)}
          className="inline-flex h-9 items-center gap-1 rounded-full bg-primary px-5 text-[14px] font-medium text-primary-foreground transition-transform duration-150 hover:bg-primary/90 focus-visible:ring-4 focus-visible:ring-ring focus-visible:outline-none active:scale-[0.98]"
        >
          See why
          <ChevronRight className="size-4" strokeWidth={2} />
        </Link>
      ) : null}
    </div>
  );
}
