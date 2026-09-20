import type { Metadata } from "next";
import { PlaygroundView } from "@/components/console/playground-view";

export const metadata: Metadata = { title: "Playground" };

export default async function PlaygroundPage({ params }: { params: Promise<{ storeId: string }> }) {
  const { storeId } = await params;
  return <PlaygroundView storeId={storeId} />;
}
