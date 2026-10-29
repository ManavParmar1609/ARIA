import type { Metadata } from "next";
import { Suspense } from "react";

import { Queue } from "@/components/console/queue";
import { LoadingRows } from "@/components/console/states";

export const metadata: Metadata = { title: "Incidents" };

export default function IncidentsPage() {
  return (
    <Suspense fallback={<LoadingRows rows={6} label="Loading incidents" />}>
      <Queue />
    </Suspense>
  );
}
