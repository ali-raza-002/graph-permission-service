"use client";

import { ErrorNotice, PageBody, PageHeader } from "@/components/console/page";

// Catches render errors inside a console page so the sidebar and toolbar stay usable.
export default function ConsoleError({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <PageBody className="space-y-6">
      <PageHeader title="Something went wrong" subtitle="This page failed to render." />
      <ErrorNotice error={error} onRetry={reset} />
    </PageBody>
  );
}
