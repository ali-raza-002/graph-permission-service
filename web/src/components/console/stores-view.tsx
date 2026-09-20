"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Database, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { EmptyState, ErrorNotice, PageBody, PageHeader } from "@/components/console/page";
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
import { keys, useStores } from "@/lib/api/hooks";
import { warden } from "@/lib/api/warden";
import { formatNumber, timeAgo } from "@/lib/format";

function CreateStoreDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [name, setName] = useState("");
  const client = useQueryClient();
  const router = useRouter();
  const create = useMutation({
    mutationFn: warden.createStore,
    onSuccess: async (store) => {
      await client.invalidateQueries({ queryKey: keys.stores });
      toast.success(`Created ${store.name}`);
      onOpenChange(false);
      router.push(`/stores/${store.id}/model`);
    },
    onError: (error) => toast.error(error.message),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="rounded-2xl sm:max-w-md">
        <form
          className="space-y-5"
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) create.mutate(name.trim());
          }}
        >
          <DialogHeader>
            <DialogTitle className="text-[17px]">New store</DialogTitle>
            <DialogDescription>
              A store holds one tenant&apos;s authorization models, tuples and decisions.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="store-name" className="text-[13px]">
              Name
            </Label>
            <Input
              id="store-name"
              autoFocus
              placeholder="Acme production"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || create.isPending}>
              Create store
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function StoresView() {
  const stores = useStores();
  const [creating, setCreating] = useState(false);

  return (
    <PageBody className="max-w-3xl">
      <PageHeader
        title="Stores"
        subtitle="Each store is an isolated authorization domain with its own model history."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus strokeWidth={1.75} />
            New store
          </Button>
        }
      />
      {stores.error ? <ErrorNotice error={stores.error} /> : null}
      <div className="divide-y divide-border overflow-hidden rounded-xl border border-border/60 bg-card shadow-xs">
        {stores.isPending
          ? Array.from({ length: 3 }, (_, i) => (
              <div key={i} className="flex h-16 items-center gap-3 px-4">
                <Skeleton className="size-9 rounded-lg" />
                <div className="space-y-2">
                  <Skeleton className="h-3.5 w-40" />
                  <Skeleton className="h-3 w-56" />
                </div>
              </div>
            ))
          : null}
        {stores.data?.items.length === 0 ? (
          <EmptyState
            icon={Database}
            title="No stores yet"
            description="Create a store, write a model, and start checking permissions."
            action={<Button onClick={() => setCreating(true)}>New store</Button>}
          />
        ) : null}
        {stores.data?.items.map((store) => (
          <Link
            key={store.id}
            href={`/stores/${store.id}`}
            className="flex min-h-16 items-center gap-3 px-4 transition-colors duration-150 hover:bg-accent/50 focus-visible:bg-accent/50 focus-visible:ring-4 focus-visible:ring-ring focus-visible:outline-none focus-visible:ring-inset"
          >
            <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Database className="size-[18px]" strokeWidth={1.75} />
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-[15px] font-medium">{store.name}</p>
              <p className="truncate font-mono text-[12px] text-muted-foreground">{store.id}</p>
            </div>
            <div className="hidden text-right sm:block">
              <p className="text-[13px] tabular-nums">rev {formatNumber(store.revision)}</p>
              <p className="text-[12px] text-muted-foreground">updated {timeAgo(store.updated_at)}</p>
            </div>
            <ChevronRight className="size-4 text-muted-foreground" strokeWidth={1.75} />
          </Link>
        ))}
      </div>
      <CreateStoreDialog open={creating} onOpenChange={setCreating} />
    </PageBody>
  );
}
