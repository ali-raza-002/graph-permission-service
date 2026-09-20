import { CheckCircle2, List, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";

export function DecisionBadge({ allowed, count }: { allowed: boolean | null; count?: number | null }) {
  if (allowed === null) {
    return (
      <Badge variant="info" className="w-20 justify-start">
        <List strokeWidth={2} />
        {count ?? 0} found
      </Badge>
    );
  }
  return allowed ? (
    <Badge variant="success" className="w-20 justify-start">
      <CheckCircle2 strokeWidth={2} />
      Allowed
    </Badge>
  ) : (
    <Badge variant="danger" className="w-20 justify-start">
      <XCircle strokeWidth={2} />
      Denied
    </Badge>
  );
}
