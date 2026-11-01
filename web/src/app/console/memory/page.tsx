import type { Metadata } from "next";
import { Suspense } from "react";

import { LibrarySkeleton } from "@/components/console/library-charts";
import { Memory } from "@/components/console/memory";
import { PageHeader } from "@/components/console/states";

export const metadata: Metadata = { title: "Incident library" };

export default function MemoryPage() {
  // The search, filters and order can come in the address (?q=, ?sev=, ?system=, ?sort=). Until
  // they are read, the page holds the shape of its figures and charts.
  return (
    <Suspense
      fallback={
        <div className="grid gap-8">
          <PageHeader
            title="Incident library"
            description="Past incidents ARIA searches when a new one comes in, by keyword and by meaning."
          />
          <LibrarySkeleton label="Loading the incident library" />
        </div>
      }
    >
      <Memory />
    </Suspense>
  );
}
