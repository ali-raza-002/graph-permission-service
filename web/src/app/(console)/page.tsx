import type { Metadata } from "next";
import { StoresView } from "@/components/console/stores-view";

export const metadata: Metadata = { title: "Stores" };

export default function StoresPage() {
  return <StoresView />;
}
