"use client";

import { CheckCircle2, ChevronLeft, Eye, FileText, FlaskConical, Pencil, Share2, Trash2, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { ErrorNotice } from "@/components/console/page";
import { AuthorizationNote, DeniedState } from "@/components/demo/authorization-note";
import { ShareDialog } from "@/components/demo/share-dialog";
import { SubjectAvatar } from "@/components/demo/subject-avatar";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ApiError } from "@/lib/api/client";
import { useAccess, useDeleteDocument, useDocument, useUpdateDocument } from "@/lib/api/workspaces-hooks";
import { WORKSPACES_STORE_ID, type DocumentDetail, type Team, type WorkspaceUser } from "@/lib/api/workspaces";
import { timeAgo } from "@/lib/format";
import { deniedDecisionId, describeSubject } from "@/lib/workspaces";
import { cn } from "@/lib/utils";

interface Directory {
  users: WorkspaceUser[];
  teams: Team[];
}

function PermissionBadges({ detail }: { detail: DocumentDetail }) {
  const { can_edit, can_share } = detail.permissions;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {can_edit ? (
        <Badge variant="success">
          <CheckCircle2 strokeWidth={2} />
          Can edit
        </Badge>
      ) : (
        <Badge variant="secondary">
          <Eye strokeWidth={2} />
          View only
        </Badge>
      )}
      {can_edit && !can_share ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <Badge variant="warning" tabIndex={0}>
              <TriangleAlert strokeWidth={2} />
              Can&apos;t reshare
            </Badge>
          </TooltipTrigger>
          <TooltipContent className="max-w-64">
            can_share is owner or (can_edit and member from org). Editors outside the org fail the second half.
          </TooltipContent>
        </Tooltip>
      ) : null}
    </div>
  );
}

function WhoCanSee({ user, documentId, directory }: { user: string; documentId: string; directory: Directory }) {
  const access = useAccess(user, documentId, true);
  if (access.isPending) return <Skeleton className="h-28 w-full rounded-xl" />;
  if (!access.data) return null;
  const viewers = access.data.effective_viewers;
  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Who can see this</h2>
        <span className="text-[12px] text-muted-foreground tabular-nums">
          {viewers.length} {viewers.length === 1 ? "person" : "people"} via ListUsers
        </span>
      </div>
      <ul className="grid gap-x-4 gap-y-1 rounded-xl border border-border/60 bg-card p-2 sm:grid-cols-2">
        {viewers.map((subject) => {
          const label = describeSubject(subject, directory.users, directory.teams);
          return (
            <li key={subject} className="flex min-h-11 items-center gap-3 rounded-lg px-2">
              <SubjectAvatar subject={label} />
              <div className="min-w-0">
                <p className="truncate text-[13px] font-medium">{label.label}</p>
                <p className="truncate text-[12px] text-muted-foreground">{label.detail}</p>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Editor({
  detail,
  user,
  onDone,
}: {
  detail: DocumentDetail;
  user: string;
  onDone: () => void;
}) {
  const [title, setTitle] = useState(detail.document.title);
  const [body, setBody] = useState(detail.document.body);
  const update = useUpdateDocument(user, detail.document.id);
  const dirty = title !== detail.document.title || body !== detail.document.body;

  const save = () => {
    if (!title.trim() || !dirty) return onDone();
    update.mutate(
      { title: title.trim(), body },
      {
        onSuccess: () => {
          toast.success("Saved");
          onDone();
        },
        onError: (error) => toast.error(error.message),
      },
    );
  };

  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        save();
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") onDone();
        if ((event.metaKey || event.ctrlKey) && (event.key === "Enter" || event.key === "s")) {
          event.preventDefault();
          save();
        }
      }}
    >
      <Input
        aria-label="Title"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        maxLength={200}
        className="h-11 text-[22px] font-semibold md:text-[22px]"
        autoFocus
      />
      <Textarea
        aria-label="Body"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        className="min-h-72 text-[15px] leading-[24px] md:text-[15px]"
      />
      <div className="flex items-center justify-end gap-2">
        <span className="mr-auto text-[12px] text-muted-foreground">⌘↵ to save · Esc to cancel</span>
        <Button type="button" variant="secondary" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={update.isPending || !title.trim()}>
          {update.isPending ? "Saving…" : "Save"}
        </Button>
      </div>
    </form>
  );
}

export function DocumentPane({
  user,
  me,
  documentId,
  orgId,
  directory,
  onBack,
  onDeleted,
  className,
}: {
  user: string;
  me: WorkspaceUser | undefined;
  documentId: string | null;
  orgId: string;
  directory: Directory;
  onBack: () => void;
  onDeleted: () => void;
  className?: string;
}) {
  const document = useDocument(user, documentId);
  const remove = useDeleteDocument(user, documentId ?? "");
  const [editing, setEditing] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const detail = document.data;
  const playground = documentId
    ? `/stores/${WORKSPACES_STORE_ID}/playground?object=${encodeURIComponent(`document:${documentId}`)}&relation=can_share&user=${encodeURIComponent(`user:${user}`)}`
    : null;

  return (
    <section aria-label="Document" className={cn("flex min-h-0 flex-col bg-background", className)}>
      <header className={cn("h-13 shrink-0 items-center gap-2 border-b border-border/60 px-4", documentId === null ? "hidden" : detail ? "flex" : "flex md:hidden")}>
        <Button variant="ghost" size="icon-sm" className="-ml-2 md:hidden" onClick={onBack} aria-label="Back to documents">
          <ChevronLeft strokeWidth={1.75} />
        </Button>
        {detail ? <PermissionBadges detail={detail} /> : null}
        <div className="ml-auto flex items-center gap-1">
          {playground && detail ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button variant="ghost" size="icon-sm" asChild>
                  <Link href={playground} aria-label="Ask Warden in the playground">
                    <FlaskConical className="size-[18px]" strokeWidth={1.75} />
                  </Link>
                </Button>
              </TooltipTrigger>
              <TooltipContent>Ask Warden in the playground</TooltipContent>
            </Tooltip>
          ) : null}
          {detail?.permissions.can_delete && !editing ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="destructive-ghost"
                  size="icon-sm"
                  aria-label="Delete document"
                  onClick={() => setConfirming(true)}
                >
                  <Trash2 className="size-[18px]" strokeWidth={1.75} />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Delete</TooltipContent>
            </Tooltip>
          ) : null}
          {detail?.permissions.can_share && !editing ? (
            <Button variant="secondary" size="sm" onClick={() => setSharing(true)}>
              <Share2 strokeWidth={1.75} />
              Share
            </Button>
          ) : null}
          {detail?.permissions.can_edit && !editing ? (
            <Button size="sm" onClick={() => setEditing(true)}>
              <Pencil strokeWidth={1.75} />
              Edit
            </Button>
          ) : null}
        </div>
      </header>

      <div className="flex flex-1 flex-col overflow-y-auto">
        {documentId === null ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
            <FileText className="size-11 text-muted-foreground/60" strokeWidth={1.5} />
            <p className="text-[17px] font-semibold">No document selected</p>
            <p className="max-w-xs text-[13px] text-muted-foreground">
              Pick a document, then switch users to watch Warden change the answer.
            </p>
          </div>
        ) : document.isPending ? (
          <div className="mx-auto max-w-3xl space-y-4 px-6 py-10 md:px-10">
            <Skeleton className="h-8 w-2/3" />
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-40 w-full" />
          </div>
        ) : document.isError ? (
          document.error instanceof ApiError && document.error.status === 404 ? (
            <DeniedState title="This document is gone" description="It may have been deleted by its owner." decisionId={null} />
          ) : document.error instanceof ApiError && document.error.status === 403 ? (
            <DeniedState
              title="You can't open this document"
              description={`Warden denied can_view for ${me?.name ?? "this user"}. The trace shows every relation it checked.`}
              decisionId={deniedDecisionId(document.error)}
            />
          ) : (
            <div className="mx-auto w-full max-w-xl px-6 py-10">
              <ErrorNotice error={document.error} onRetry={() => void document.refetch()} />
            </div>
          )
        ) : detail ? (
          <article className="mx-auto max-w-3xl space-y-10 px-6 py-10 md:px-10">
            {editing ? (
              <Editor key={detail.document.id} detail={detail} user={user} onDone={() => setEditing(false)} />
            ) : (
              <div className="space-y-4">
                <div className="space-y-1">
                  <h1 className="text-[28px] leading-[34px] font-semibold tracking-tight">{detail.document.title}</h1>
                  <p className="text-[13px] text-muted-foreground">
                    Created by {describeSubject(`user:${detail.document.created_by}`, directory.users, []).label} ·
                    edited {timeAgo(detail.document.updated_at)}
                  </p>
                </div>
                <div className="text-[17px] leading-[26px] tracking-[-0.01em] whitespace-pre-wrap">
                  {detail.document.body || <span className="text-muted-foreground">This document is empty.</span>}
                </div>
              </div>
            )}
            <WhoCanSee user={user} documentId={detail.document.id} directory={directory} />
            <AuthorizationNote authorization={detail.authorization} relation="can_view" className="-mx-2" />
          </article>
        ) : null}
      </div>

      {detail ? (
        <>
          <ShareDialog
            user={user}
            documentId={detail.document.id}
            title={detail.document.title}
            orgId={orgId}
            users={directory.users}
            teams={directory.teams}
            open={sharing}
            onOpenChange={setSharing}
          />
          <AlertDialog open={confirming} onOpenChange={setConfirming}>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Delete “{detail.document.title}”?</AlertDialogTitle>
                <AlertDialogDescription>
                  The document and all of its relationship tuples are removed. This can&apos;t be undone.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  className="bg-destructive text-white hover:bg-destructive/90"
                  onClick={() =>
                    remove.mutate(undefined, {
                      onSuccess: () => {
                        toast.success("Document deleted");
                        onDeleted();
                      },
                      onError: (error) => toast.error(error.message),
                    })
                  }
                >
                  Delete
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </>
      ) : null}
    </section>
  );
}
