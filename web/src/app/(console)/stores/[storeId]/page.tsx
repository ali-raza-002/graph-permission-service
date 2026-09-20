import { OverviewView } from "@/components/console/overview-view";

export default async function OverviewPage({ params }: { params: Promise<{ storeId: string }> }) {
  const { storeId } = await params;
  return <OverviewView storeId={storeId} />;
}
