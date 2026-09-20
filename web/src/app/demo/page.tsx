import type { Metadata } from "next";
import { Suspense } from "react";
import { WorkspacesApp } from "@/components/demo/workspaces-app";

export const metadata: Metadata = {
  title: "Workspaces demo",
  description: "A shared-documents app whose every permission decision is delegated to Warden.",
};

export default function DemoPage() {
  return (
    <Suspense>
      <WorkspacesApp />
    </Suspense>
  );
}
