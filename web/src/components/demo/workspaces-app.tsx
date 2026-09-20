"use client";

import { LayoutPanelLeft, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect } from "react";
import { DocumentPane } from "@/components/demo/document-pane";
import { DocumentsColumn } from "@/components/demo/documents-column";
import { FolderColumn } from "@/components/demo/folder-column";
import { UserSwitcher } from "@/components/demo/user-switcher";
import { ErrorNotice } from "@/components/console/page";
import { ThemeToggle } from "@/components/console/theme-toggle";
import { Button } from "@/components/ui/button";
import { useFolders, useTeams, useWorkspaceUsers } from "@/lib/api/workspaces-hooks";
import { WORKSPACES_STORE_ID } from "@/lib/api/workspaces";
import { cn } from "@/lib/utils";

const DEFAULT_USER = "anne";

type Pane = "folders" | "documents" | "document";

function useDemoLocation() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const user = params.get("as") ?? DEFAULT_USER;
  const folder = params.get("folder");
  const doc = params.get("doc");

  const navigate = useCallback(
    (next: { as?: string; folder?: string | null; doc?: string | null }) => {
      const query = new URLSearchParams(params.toString());
      for (const [key, value] of Object.entries(next)) {
        if (value === null || value === undefined) query.delete(key);
        else query.set(key, value);
      }
      router.replace(`${pathname}?${query.toString()}`, { scroll: false });
    },
    [params, pathname, router],
  );

  return { user, folder, doc, navigate };
}

export function WorkspacesApp() {
  const { user, folder, doc, navigate } = useDemoLocation();
  const users = useWorkspaceUsers();
  const teams = useTeams();
  const folders = useFolders(user);

  const me = users.data?.find((u) => u.handle === user);
  const visible = folders.data ?? [];
  const firstFolder = visible[0]?.id ?? null;

  useEffect(() => {
    if (folder === null && firstFolder !== null) navigate({ folder: firstFolder });
  }, [folder, firstFolder, navigate]);

  const pane: Pane = doc ? "document" : folder ? "documents" : "folders";
  const orgId = visible.find((f) => f.id === folder)?.org_id ?? visible[0]?.org_id ?? "lumen";
  const failure = users.error ?? folders.error;

  return (
    <div className="flex h-dvh flex-col bg-background">
      <header className="sticky top-0 z-40 flex h-13 shrink-0 items-center gap-3 border-b border-border/60 bg-background/72 px-4 backdrop-blur-xl backdrop-saturate-[1.8]">
        <div className="flex size-7 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <LayoutPanelLeft className="size-4" strokeWidth={1.75} />
        </div>
        <div className="flex min-w-0 items-baseline gap-2">
          <span className="text-[15px] font-semibold">Workspaces</span>
          <span className="hidden truncate text-[13px] text-muted-foreground sm:inline">Lumen Labs</span>
        </div>
        <p className="mx-auto hidden items-center gap-1.5 text-[12px] text-muted-foreground lg:flex">
          <ShieldCheck className="size-3.5 text-primary" strokeWidth={1.75} />
          Every permission on this page is decided by Warden
        </p>
        <div className="ml-auto flex items-center gap-1 lg:ml-0">
          <UserSwitcher users={users.data ?? []} current={user} onChange={(handle) => navigate({ as: handle })} />
          <ThemeToggle />
          <Button variant="ghost" size="sm" asChild className="hidden sm:inline-flex">
            <Link href={`/stores/${WORKSPACES_STORE_ID}`}>Open console</Link>
          </Button>
        </div>
      </header>

      {failure ? (
        <div className="mx-auto w-full max-w-xl p-6">
          <ErrorNotice error={failure} />
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 md:grid-cols-[220px_280px_1fr] lg:grid-cols-[240px_320px_1fr]">
          <FolderColumn
            folders={visible}
            loading={folders.isPending}
            selected={folder}
            onSelect={(id) => navigate({ folder: id, doc: null })}
            userName={me?.name.split(" ")[0] ?? user}
            className={cn(pane === "folders" ? "flex" : "hidden md:flex")}
          />
          <DocumentsColumn
            user={user}
            me={me}
            folderId={folder}
            selected={doc}
            onSelect={(id) => navigate({ doc: id })}
            onBack={() => navigate({ folder: null, doc: null })}
            className={cn(pane === "documents" ? "flex" : "hidden md:flex")}
          />
          <DocumentPane
            key={`${user}:${doc ?? ""}`}
            user={user}
            me={me}
            documentId={doc}
            orgId={orgId}
            directory={{ users: users.data ?? [], teams: teams.data ?? [] }}
            onBack={() => navigate({ doc: null })}
            onDeleted={() => navigate({ doc: null })}
            className={cn(pane === "document" ? "flex" : "hidden md:flex")}
          />
        </div>
      )}
    </div>
  );
}
