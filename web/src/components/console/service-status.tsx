"use client";

import { useQuery } from "@tanstack/react-query";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { warden } from "@/lib/api/warden";
import { cn } from "@/lib/utils";

export function ServiceStatus() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: warden.health,
    refetchInterval: 20_000,
    retry: false,
  });
  const up = health.isSuccess;
  const label = health.isPending ? "Connecting" : up ? `API ${health.data.version}` : "API offline";
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div
          className="flex items-center gap-2 rounded-md px-1.5 py-1 text-[12px] text-muted-foreground"
          role="status"
          aria-live="polite"
        >
          <span
            className={cn(
              "size-2 rounded-full",
              health.isPending ? "bg-muted-foreground/40" : up ? "bg-success" : "bg-destructive",
            )}
          />
          <span className="group-data-[collapsible=icon]:hidden">{label}</span>
        </div>
      </TooltipTrigger>
      <TooltipContent side="top">{up ? "Warden API is reachable" : "Warden API is not reachable"}</TooltipContent>
    </Tooltip>
  );
}
