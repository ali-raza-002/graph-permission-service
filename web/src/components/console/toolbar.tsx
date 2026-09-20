"use client";

import { useParams, usePathname } from "next/navigation";
import { Separator } from "@/components/ui/separator";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { useStores } from "@/lib/api/hooks";

const TITLES: Record<string, string> = {
  model: "Model",
  tuples: "Tuples",
  playground: "Playground",
  decisions: "Decisions",
};

export function ConsoleToolbar() {
  const pathname = usePathname();
  const { storeId } = useParams<{ storeId?: string }>();
  const stores = useStores();
  const store = stores.data?.items.find((s) => s.id === storeId);
  const section = pathname.split("/")[3];
  const title = storeId ? (section ? (TITLES[section] ?? "Overview") : "Overview") : "Stores";

  return (
    <header className="sticky top-0 z-30 flex h-13 shrink-0 items-center gap-2 border-b border-border/60 bg-background/72 px-4 backdrop-blur-xl backdrop-saturate-[1.8]">
      <SidebarTrigger className="-ml-1" aria-label="Toggle sidebar" />
      <Separator orientation="vertical" className="mr-1 data-[orientation=vertical]:h-4" />
      <div className="flex min-w-0 items-baseline gap-2">
        <p className="truncate text-[15px] font-semibold">{title}</p>
        {store ? <span className="truncate text-[13px] text-muted-foreground">{store.name}</span> : null}
      </div>
    </header>
  );
}
