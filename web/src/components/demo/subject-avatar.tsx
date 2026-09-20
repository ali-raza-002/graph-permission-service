import { Building2, Globe, Users } from "lucide-react";
import type { SubjectLabel } from "@/lib/workspaces";
import { cn } from "@/lib/utils";

const ICONS = { team: Users, org: Building2, public: Globe } as const;

export function SubjectAvatar({ subject, className }: { subject: SubjectLabel; className?: string }) {
  const base = "flex size-7 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold";
  if (subject.kind === "user") {
    return (
      <span aria-hidden className={cn(base, "bg-primary/12 text-primary", className)}>
        {subject.initials}
      </span>
    );
  }
  const Icon = ICONS[subject.kind];
  return (
    <span aria-hidden className={cn(base, "bg-secondary text-muted-foreground", className)}>
      <Icon className="size-3.5" strokeWidth={1.75} />
    </span>
  );
}
