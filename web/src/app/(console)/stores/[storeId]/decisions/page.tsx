import type { Metadata } from "next";
import { DecisionsView } from "@/components/console/decisions-view";

export const metadata: Metadata = { title: "Decisions" };

export default async function DecisionsPage({ params }: { params: Promise<{ storeId: string }> }) {
  const { storeId } = await params;
  return <DecisionsView storeId={storeId} />;
}
