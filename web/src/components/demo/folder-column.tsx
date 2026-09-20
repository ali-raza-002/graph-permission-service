"use client";

import { FolderClosed, FolderOpen } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import type { Folder } from "@/lib/api/workspaces";
import { folderTree } from "@/lib/workspaces";
import { cn } from "@/lib/utils";

export function FolderColumn({
  folders,
  loading,
  selected,
  onSelect,
  userName,
  className,
}: {
  folders: Folder[];
  loading: boolean;
  selected: string | null;
  onSelect: (id: string) => void;
  userName: string;
  className?: string;
}) {
  const tree = folderTree(folders);
  return (
    <nav
      aria-label="Folders"
      className={cn(
        "flex min-h-0 flex-col border-r border-border/60 bg-sidebar/80 backdrop-blur-2xl backdrop-saturate-150",
        className,
      )}
    >
      <div className="flex-1 overflow-y-auto px-2 py-4">
        <h2 className="px-2 pb-2 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Folders</h2>
        {loading ? (
          <div className="space-y-1.5 px-2">
            {Array.from({ length: 5 }, (_, i) => (
              <Skeleton key={i} className="h-7 w-full rounded-md" />
            ))}
          </div>
        ) : (
          <ul className="space-y-0.5">
            {tree.map(({ folder, depth }) => {
              const active = folder.id === selected;
              const Icon = active ? FolderOpen : FolderClosed;
              return (
                <li key={folder.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(folder.id)}
                    aria-current={active ? "page" : undefined}
                    style={{ paddingLeft: 8 + depth * 16 }}
                    className={cn(
                      "flex h-8 w-full items-center gap-2 rounded-md pr-2 text-left text-[13px] transition-colors duration-150 focus-visible:ring-4 focus-visible:ring-ring focus-visible:outline-none",
                      active ? "bg-sidebar-accent font-medium" : "hover:bg-sidebar-accent/60",
                    )}
                  >
                    <Icon className={cn("size-4 shrink-0", active ? "text-primary" : "text-muted-foreground")} strokeWidth={1.75} />
                    <span className="truncate">{folder.name}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
      <p className="border-t border-border/60 px-4 py-3 text-[12px] leading-4 text-muted-foreground">
        {loading
          ? "Asking Warden which folders you can see…"
          : `${userName} can see ${folders.length} ${folders.length === 1 ? "folder" : "folders"}. Warden's ListObjects decides what appears here.`}
      </p>
    </nav>
  );
}
