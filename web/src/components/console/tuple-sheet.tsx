"use client";

import { Loader2 } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { ApiError } from "@/lib/api/client";
import { useWriteTuples } from "@/lib/api/hooks";
import type { AuthorizationModel, Rewrite, TypeRestriction } from "@/lib/api/schemas";

function restrictions(rewrite: Rewrite): TypeRestriction[] {
  switch (rewrite.kind) {
    case "direct":
      return rewrite.types;
    case "union":
    case "intersection":
      return rewrite.children.flatMap(restrictions);
    case "exclusion":
      return [...restrictions(rewrite.base), ...restrictions(rewrite.subtract)];
    default:
      return [];
  }
}

export function assignableRelations(model: AuthorizationModel | undefined, type: string) {
  const def = model?.types.find((t) => t.name === type);
  return (def?.relations ?? [])
    .map((r) => ({ name: r.name, accepts: restrictions(r.rewrite) }))
    .filter((r) => r.accepts.length > 0);
}

function describe(r: TypeRestriction): string {
  if (r.wildcard) return `${r.type}:*`;
  return r.relation ? `${r.type}:<id>#${r.relation}` : `${r.type}:<id>`;
}

export function TupleSheet({
  storeId,
  model,
  open,
  onOpenChange,
}: {
  storeId: string;
  model: AuthorizationModel | undefined;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const types = model?.types.filter((t) => assignableRelations(model, t.name).length > 0) ?? [];
  const [type, setType] = useState("");
  const [objectId, setObjectId] = useState("");
  const [relation, setRelation] = useState("");
  const [user, setUser] = useState("");
  const [error, setError] = useState<string | null>(null);
  const write = useWriteTuples(storeId);

  const relations = useMemo(() => assignableRelations(model, type), [model, type]);
  const accepted = relations.find((r) => r.name === relation)?.accepts ?? [];

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    write.mutate(
      { writes: [{ object: `${type}:${objectId.trim()}`, relation, user: user.trim() }] },
      {
        onSuccess: (result) => {
          toast.success(`Written at revision ${result.revision}`);
          setObjectId("");
          setUser("");
          onOpenChange(false);
        },
        onError: (err) => {
          const reason =
            err instanceof ApiError && typeof err.details[0]?.reason === "string" ? err.details[0].reason : null;
          setError(reason ?? err.message);
        },
      },
    );
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full gap-0 sm:max-w-md">
        <form onSubmit={submit} className="flex h-full flex-col">
          <SheetHeader className="border-b border-border/60 px-6 py-5">
            <SheetTitle className="text-[17px]">Add tuple</SheetTitle>
            <SheetDescription>
              Relationships are validated against the latest model before they are written.
            </SheetDescription>
          </SheetHeader>
          <div className="flex-1 space-y-5 overflow-y-auto px-6 py-6">
            <div className="grid grid-cols-[140px_1fr] gap-3">
              <div className="space-y-1.5">
                <Label className="text-[13px]">Object type</Label>
                <Select
                  value={type}
                  onValueChange={(value) => {
                    setType(value);
                    setRelation("");
                  }}
                >
                  <SelectTrigger className="w-full" aria-label="Object type">
                    <SelectValue placeholder="Type" />
                  </SelectTrigger>
                  <SelectContent>
                    {types.map((t) => (
                      <SelectItem key={t.name} value={t.name}>
                        {t.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tuple-object-id" className="text-[13px]">
                  Object id
                </Label>
                <Input
                  id="tuple-object-id"
                  placeholder="roadmap"
                  value={objectId}
                  onChange={(e) => setObjectId(e.target.value)}
                  className="font-mono"
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label className="text-[13px]">Relation</Label>
              <Select value={relation} onValueChange={setRelation} disabled={!type}>
                <SelectTrigger className="w-full" aria-label="Relation">
                  <SelectValue placeholder={type ? "Choose a relation" : "Choose a type first"} />
                </SelectTrigger>
                <SelectContent>
                  {relations.map((r) => (
                    <SelectItem key={r.name} value={r.name}>
                      {r.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tuple-user" className="text-[13px]">
                User
              </Label>
              <Input
                id="tuple-user"
                placeholder="user:anne"
                value={user}
                onChange={(e) => setUser(e.target.value)}
                className="font-mono"
              />
              <p className="text-[12px] text-muted-foreground">
                {accepted.length > 0
                  ? `Accepts ${accepted.map(describe).join(", ")}`
                  : "A subject such as user:anne, team:eng#member or user:*"}
              </p>
            </div>
            {error ? (
              <p role="alert" className="rounded-lg bg-destructive/8 px-3 py-2 text-[13px] text-destructive">
                {error}
              </p>
            ) : null}
          </div>
          <SheetFooter className="flex-row justify-end gap-2 border-t border-border/60 px-6 py-4">
            <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!type || !objectId.trim() || !relation || !user.trim() || write.isPending}>
              {write.isPending ? <Loader2 className="motion-safe:animate-spin" /> : null}
              Write tuple
            </Button>
          </SheetFooter>
        </form>
      </SheetContent>
    </Sheet>
  );
}
