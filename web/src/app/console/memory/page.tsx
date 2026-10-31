import type { Metadata } from "next";
import { Suspense } from "react";

import { Memory } from "@/components/console/memory";
import { LoadingRows } from "@/components/console/states";

export const metadata: Metadata = { title: "Incident library" };

export default function MemoryPage() {
  // The search can come in the address (?q=, ?system=).
  return (
    <Suspense fallback={<LoadingRows rows={6} label="Loading the incident library" />}>
      <Memory />
    </Suspense>
  );
}
