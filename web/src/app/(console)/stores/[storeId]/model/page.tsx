import type { Metadata } from "next";
import { ModelView } from "@/components/console/model-view";

export const metadata: Metadata = { title: "Model" };

export default async function ModelPage({ params }: { params: Promise<{ storeId: string }> }) {
  const { storeId } = await params;
  return <ModelView storeId={storeId} />;
}
