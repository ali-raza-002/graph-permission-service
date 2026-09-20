"use client";

import {
  AppWindow,
  Braces,
  Check,
  ChevronsUpDown,
  FlaskConical,
  LayoutDashboard,
  Rows3,
  ScrollText,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { ThemeToggle } from "@/components/console/theme-toggle";
import { ServiceStatus } from "@/components/console/service-status";
import { useStores } from "@/lib/api/hooks";

const STORE_NAV = [
  { segment: "", label: "Overview", icon: LayoutDashboard },
  { segment: "model", label: "Model", icon: Braces },
  { segment: "tuples", label: "Tuples", icon: Rows3 },
  { segment: "playground", label: "Playground", icon: FlaskConical },
  { segment: "decisions", label: "Decisions", icon: ScrollText },
] as const;

function StoreSwitcher({ storeId }: { storeId: string | undefined }) {
  const stores = useStores();
  const router = useRouter();
  const current = stores.data?.items.find((s) => s.id === storeId);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <SidebarMenuButton size="lg" className="data-[state=open]:bg-sidebar-accent">
          <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <ShieldCheck className="size-[18px]" strokeWidth={1.75} />
          </div>
          <div className="grid flex-1 text-left leading-tight">
            <span className="truncate text-[13px] font-semibold">Warden</span>
            <span className="truncate text-[12px] text-muted-foreground">
              {current?.name ?? (storeId ? "Loading…" : "Choose a store")}
            </span>
          </div>
          <ChevronsUpDown className="ml-auto size-4 text-muted-foreground" strokeWidth={1.75} />
        </SidebarMenuButton>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-60 rounded-xl" align="start" sideOffset={6}>
        <DropdownMenuLabel className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
          Stores
        </DropdownMenuLabel>
        {stores.data?.items.map((store) => (
          <DropdownMenuItem key={store.id} onSelect={() => router.push(`/stores/${store.id}`)}>
            <span className="truncate">{store.name}</span>
            {store.id === storeId ? <Check className="ml-auto size-4" /> : null}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => router.push("/")}>All stores</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function AppSidebar() {
  const params = useParams<{ storeId?: string }>();
  const pathname = usePathname();
  const storeId = params.storeId;

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <StoreSwitcher storeId={storeId} />
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        {storeId ? (
          <SidebarGroup>
            <SidebarGroupLabel className="text-[11px] tracking-wide uppercase">Store</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {STORE_NAV.map((item) => {
                  const href = `/stores/${storeId}${item.segment ? `/${item.segment}` : ""}`;
                  const active = item.segment ? pathname.startsWith(href) : pathname === href;
                  return (
                    <SidebarMenuItem key={item.label}>
                      <SidebarMenuButton asChild isActive={active} tooltip={item.label}>
                        <Link href={href}>
                          <item.icon strokeWidth={1.75} />
                          <span>{item.label}</span>
                        </Link>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  );
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ) : null}
        <SidebarGroup>
          <SidebarGroupLabel className="text-[11px] tracking-wide uppercase">Demo</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton asChild tooltip="Workspaces app">
                  <Link href="/demo">
                    <AppWindow strokeWidth={1.75} />
                    <span>Workspaces app</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <div className="flex items-center justify-between gap-2 px-1 group-data-[collapsible=icon]:flex-col">
          <ServiceStatus />
          <ThemeToggle />
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
