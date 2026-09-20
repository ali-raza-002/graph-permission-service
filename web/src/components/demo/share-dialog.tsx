"use client";

import { X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { SubjectAvatar } from "@/components/demo/subject-avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAccess, useShare } from "@/lib/api/workspaces-hooks";
import { roles, type Role, type Team, type WorkspaceUser } from "@/lib/api/workspaces";
import { describeSubject, type SubjectKind } from "@/lib/workspaces";

// Mirrors the direct type restrictions on document#viewer, #editor and #blocked.
const ACCEPTS: Record<Role, SubjectKind[]> = {
  viewer: ["user", "team", "org", "public"],
  editor: ["user", "team"],
  blocked: ["user"],
};

const ROLE_LABEL: Record<Role, string> = { viewer: "Viewer", editor: "Editor", blocked: "Blocked" };

const isRole = (value: string): value is Role => (roles as readonly string[]).includes(value);

const ROLE_BADGE = { viewer: "secondary", editor: "info", blocked: "danger" } as const;

export function ShareDialog({
  user,
  documentId,
  title,
  orgId,
  users,
  teams,
  open,
  onOpenChange,
}: {
  user: string;
  documentId: string;
  title: string;
  orgId: string;
  users: WorkspaceUser[];
  teams: Team[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const access = useAccess(user, documentId, open);
  const share = useShare(user, documentId);
  const [role, setRole] = useState<Role>("viewer");
  const [subject, setSubject] = useState("");

  // Blocking and revoking need can_manage_access (owner or org admin); other sharers only add.
  const canManage = access.data?.can_manage ?? false;
  const available = roles.filter((r) => canManage || r !== "blocked");
  const accepts = ACCEPTS[role];
  const options = [
    { group: "People", kind: "user" as const, subjects: users.map((u) => `user:${u.handle}`) },
    { group: "Teams", kind: "team" as const, subjects: teams.map((t) => `team:${t.id}#member`) },
    { group: "Groups", kind: "org" as const, subjects: [`org:${orgId}#member`] },
    { group: "Public", kind: "public" as const, subjects: ["user:*"] },
  ].filter((o) => accepts.includes(o.kind));

  const changeRole = (next: string) => {
    if (!isRole(next)) return;
    setRole(next);
    if (subject && !ACCEPTS[next].includes(describeSubject(subject, users, teams).kind)) setSubject("");
  };

  const apply = (target: { subject: string; role: Role }, remove: boolean) =>
    share.mutate(
      { share: target, remove },
      {
        onSuccess: () => {
          const who = describeSubject(target.subject, users, teams).label;
          toast.success(remove ? `Removed ${who}` : `${who} is now ${target.role === "blocked" ? "blocked" : `a ${target.role}`}`);
          if (!remove) setSubject("");
        },
        onError: (error) => toast.error(error.message),
      },
    );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="text-[17px]">Share “{title}”</DialogTitle>
          <DialogDescription className="text-[13px]">
            Every change is a tuple write. Warden returns a new revision and the next check reads at least that fresh.
          </DialogDescription>
        </DialogHeader>

        <form
          className="grid gap-3 sm:grid-cols-[1fr_auto]"
          onSubmit={(event) => {
            event.preventDefault();
            if (subject) apply({ subject, role }, false);
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="share-subject" className="text-[13px]">
              Person or group
            </Label>
            <Select value={subject} onValueChange={setSubject}>
              <SelectTrigger id="share-subject" className="w-full">
                <SelectValue placeholder="Choose who to add" />
              </SelectTrigger>
              <SelectContent>
                {options.map((option) => (
                  <SelectGroup key={option.group}>
                    <SelectLabel className="text-[11px] tracking-wide uppercase">{option.group}</SelectLabel>
                    {option.subjects.map((s) => (
                      <SelectItem key={s} value={s}>
                        {describeSubject(s, users, teams).label}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <span className="block text-[13px] font-medium" id="share-role">
              Role
            </span>
            <Tabs value={role} onValueChange={changeRole} aria-labelledby="share-role">
              <TabsList className="h-9">
                {available.map((r) => (
                  <TabsTrigger key={r} value={r} className="px-3">
                    {ROLE_LABEL[r]}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          </div>
          <p className="text-[12px] text-muted-foreground sm:col-span-2">
            {role === "blocked"
              ? "Blocked users lose access even when a folder or team would grant it: can_view is viewer but not blocked."
              : role === "editor"
                ? "Editors can change the document. Only org members can reshare it."
                : "Viewers can read the document and see who else has access."}
          </p>
          <DialogFooter className="sm:col-span-2">
            <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
              Done
            </Button>
            <Button type="submit" disabled={!subject || share.isPending}>
              {share.isPending ? "Saving…" : "Add"}
            </Button>
          </DialogFooter>
        </form>

        <section className="space-y-2">
          <h3 className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">Direct access</h3>
          {access.isPending ? (
            <Skeleton className="h-24 w-full rounded-xl" />
          ) : access.data ? (
            <ul className="divide-y divide-border rounded-xl border border-border/60 bg-card">
              {access.data.owner.map((owner) => {
                const label = describeSubject(owner, users, teams);
                return (
                  <li key={`owner-${owner}`} className="flex min-h-11 items-center gap-3 px-3">
                    <SubjectAvatar subject={label} />
                    <span className="min-w-0 flex-1 truncate text-[13px]">{label.label}</span>
                    <span className="text-[12px] text-muted-foreground">Owner</span>
                  </li>
                );
              })}
              {access.data.shares.map((s) => {
                const label = describeSubject(s.subject, users, teams);
                return (
                  <li key={`${s.role}-${s.subject}`} className="flex min-h-11 items-center gap-3 px-3">
                    <SubjectAvatar subject={label} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13px]">{label.label}</p>
                      <p className="truncate font-mono text-[11px] text-muted-foreground">{s.subject}</p>
                    </div>
                    <Badge variant={ROLE_BADGE[s.role]}>{ROLE_LABEL[s.role]}</Badge>
                    {canManage ? (
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`Remove ${label.label} as ${s.role}`}
                        disabled={share.isPending}
                        onClick={() => apply(s, true)}
                      >
                        <X className="size-4" strokeWidth={1.75} />
                      </Button>
                    ) : null}
                  </li>
                );
              })}
              {access.data.shares.length === 0 ? (
                <li className="px-3 py-3 text-[13px] text-muted-foreground">
                  No direct shares. Access comes from the folder and its parents.
                </li>
              ) : null}
            </ul>
          ) : null}
          {access.data && !access.data.can_manage ? (
            <p className="text-[12px] text-muted-foreground">
              Only the owner or an org admin can block people or remove access (can_manage_access).
            </p>
          ) : null}
          {access.isPending || access.data ? null : (
            <p role="alert" className="text-[13px] text-destructive">
              {access.error?.message ?? "Could not load access."}
            </p>
          )}
        </section>
      </DialogContent>
    </Dialog>
  );
}
