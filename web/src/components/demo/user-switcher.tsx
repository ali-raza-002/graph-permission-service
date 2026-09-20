"use client";

import { Check, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SubjectAvatar } from "@/components/demo/subject-avatar";
import type { WorkspaceUser } from "@/lib/api/workspaces";
import { describeSubject } from "@/lib/workspaces";

export function UserSwitcher({
  users,
  current,
  onChange,
}: {
  users: WorkspaceUser[];
  current: string;
  onChange: (handle: string) => void;
}) {
  const me = users.find((u) => u.handle === current);
  const label = (u: WorkspaceUser) => describeSubject(`user:${u.handle}`, users, []);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="h-9 gap-2 rounded-full pr-2.5 pl-1" aria-label="Switch user">
          {me ? <SubjectAvatar subject={label(me)} /> : null}
          <span className="hidden text-[13px] sm:inline">{me?.name ?? "Choose a user"}</span>
          <ChevronDown className="size-3.5 text-muted-foreground" strokeWidth={2} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" sideOffset={8} className="w-72 rounded-xl p-1">
        <DropdownMenuLabel className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
          View the workspace as
        </DropdownMenuLabel>
        {users.map((user) => (
          <DropdownMenuItem key={user.handle} onSelect={() => onChange(user.handle)} className="gap-3 py-1.5">
            <SubjectAvatar subject={label(user)} />
            <div className="min-w-0">
              <p className="truncate text-[13px] font-medium">{user.name}</p>
              <p className="truncate text-[12px] text-muted-foreground">{user.title}</p>
            </div>
            {user.handle === current ? <Check className="ml-auto size-4" strokeWidth={2} /> : null}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
