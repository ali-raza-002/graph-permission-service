"use client";

import { ChevronLeft, FileText, Lock, Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { ErrorNotice } from "@/components/console/page";
import { AuthorizationNote, DeniedState } from "@/components/demo/authorization-note";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ApiError } from "@/lib/api/client";
import { useCreateDocument, useFolder } from "@/lib/api/workspaces-hooks";
import type { WorkspaceUser } from "@/lib/api/workspaces";
import { timeAgo } from "@/lib/format";
import { deniedDecisionId } from "@/lib/workspaces";
import { cn } from "@/lib/utils";

function NewDocumentDialog({
  user,
  folderId,
  open,
  onOpenChange,
  onCreated,
}: {
  user: string;
  folderId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (id: string) => void;
}) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const create = useCreateDocument(user, folderId);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    create.mutate(
      { title: title.trim(), body },
      {
        onSuccess: (detail) => {
          toast.success("Document created. You are its owner.");
          setTitle("");
          setBody("");
          onOpenChange(false);
          onCreated(detail.document.id);
        },
        onError: (error) => toast.error(error.message),
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit} className="space-y-5">
          <DialogHeader>
            <DialogTitle className="text-[17px]">New document</DialogTitle>
            <DialogDescription className="text-[13px]">
              Creating it writes three tuples to Warden: parent folder, org and you as owner.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="doc-title" className="text-[13px]">
              Title
            </Label>
            <Input id="doc-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="doc-body" className="text-[13px]">
              Body
            </Label>
            <Textarea id="doc-body" value={body} onChange={(e) => setBody(e.target.value)} className="min-h-32" />
          </div>
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!title.trim() || create.isPending}>
              {create.isPending ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function DocumentsColumn({
  user,
  me,
  folderId,
  selected,
  onSelect,
  onBack,
  className,
}: {
  user: string;
  me: WorkspaceUser | undefined;
  folderId: string | null;
  selected: string | null;
  onSelect: (id: string) => void;
  onBack: () => void;
  className?: string;
}) {
  const folder = useFolder(user, folderId);
  const [creating, setCreating] = useState(false);
  const detail = folder.data;

  return (
    <section aria-label="Documents" className={cn("flex min-h-0 flex-col border-r border-border/60 bg-background", className)}>
      <header className="flex items-start gap-2 border-b border-border/60 px-4 py-3">
        <Button variant="ghost" size="icon-sm" className="-ml-2 md:hidden" onClick={onBack} aria-label="Back to folders">
          <ChevronLeft strokeWidth={1.75} />
        </Button>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-[17px] leading-[22px] font-semibold">
            {detail?.folder.name ??
              (folder.error instanceof ApiError && folder.error.status === 403 ? "No access" : "\u00a0")}
          </h2>
          <p className="truncate text-[12px] text-muted-foreground">{detail?.folder.description ?? "\u00a0"}</p>
        </div>
        {detail ? (
          detail.can_create ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon-sm" onClick={() => setCreating(true)} aria-label="New document">
                  <Plus className="size-[18px]" strokeWidth={1.75} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>New document</TooltipContent>
            </Tooltip>
          ) : (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="mt-1 flex h-6 items-center gap-1 rounded-full bg-secondary px-2 text-[11px] font-medium text-muted-foreground">
                  <Lock className="size-3" strokeWidth={2} />
                  Read only
                </span>
              </TooltipTrigger>
              <TooltipContent>{me?.name ?? "You"} is not an editor of this folder</TooltipContent>
            </Tooltip>
          )
        ) : null}
      </header>

      {folderId === null ? (
        <div className="flex flex-1 items-center justify-center p-6 text-center text-[13px] text-muted-foreground">
          Choose a folder.
        </div>
      ) : folder.isPending ? (
        <div className="space-y-3 p-4">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="space-y-1.5">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-3 w-1/3" />
            </div>
          ))}
        </div>
      ) : folder.isError ? (
        folder.error instanceof ApiError && folder.error.status === 403 ? (
          <DeniedState
            title="You can't open this folder"
            description={`Warden says ${me?.name ?? "this user"} is not a viewer here.`}
            decisionId={deniedDecisionId(folder.error)}
          />
        ) : (
          <div className="p-4">
            <ErrorNotice error={folder.error} onRetry={() => void folder.refetch()} />
          </div>
        )
      ) : (
        <>
          <ul className="flex-1 space-y-0.5 overflow-y-auto p-2">
            {detail?.documents.length === 0 ? (
              <li className="flex flex-col items-center gap-2 px-4 py-12 text-center">
                <FileText className="size-9 text-muted-foreground/60" strokeWidth={1.5} />
                <p className="text-[13px] text-muted-foreground">
                  {detail.can_create ? "No documents yet. Create the first one." : "Nothing here you can read."}
                </p>
              </li>
            ) : null}
            {detail?.documents.map((doc) => {
              const active = doc.id === selected;
              return (
                <li key={doc.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(doc.id)}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "w-full rounded-lg px-3 py-2 text-left transition-colors duration-150 focus-visible:ring-4 focus-visible:ring-ring focus-visible:outline-none",
                      active ? "bg-primary/10" : "hover:bg-accent/50",
                    )}
                  >
                    <p className="truncate text-[14px] font-medium">{doc.title}</p>
                    <p className="truncate text-[12px] text-muted-foreground">
                      {doc.created_by} · edited {timeAgo(doc.updated_at)}
                    </p>
                  </button>
                </li>
              );
            })}
          </ul>
          {detail ? (
            <div className="border-t border-border/60 p-2">
              <AuthorizationNote authorization={detail.authorization} relation="viewer" />
            </div>
          ) : null}
        </>
      )}

      {folderId !== null ? (
        <NewDocumentDialog
          user={user}
          folderId={folderId}
          open={creating}
          onOpenChange={setCreating}
          onCreated={onSelect}
        />
      ) : null}
    </section>
  );
}
