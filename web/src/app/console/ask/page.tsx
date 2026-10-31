import type { Metadata } from "next";
import { Suspense } from "react";

import { Ask } from "@/components/console/ask";
import { LoadingRows } from "@/components/console/states";

export const metadata: Metadata = { title: "Ask ARIA" };

export default function AskPage() {
  // The incident to ask about can come in the address (?run=).
  return (
    <Suspense fallback={<LoadingRows rows={4} label="Loading Ask ARIA" />}>
      <Ask />
    </Suspense>
  );
}
