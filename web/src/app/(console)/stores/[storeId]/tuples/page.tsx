import type { Metadata } from "next";
import { TuplesView } from "@/components/console/tuples-view";

export const metadata: Metadata = { title: "Tuples" };

export default async function TuplesPage({ params }: { params: Promise<{ storeId: string }> }) {
  const { storeId } = await params;
  return <TuplesView storeId={storeId} />;
}
