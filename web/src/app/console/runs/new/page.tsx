import type { Metadata } from "next";
import { Suspense } from "react";

import { NewRun } from "@/components/console/new-run";
import { LoadingRows } from "@/components/console/states";

export const metadata: Metadata = { title: "New triage" };

// A public demo (ARIA_PUBLIC_DEMO=1, read when the page is built) reminds visitors that pasted
// logs pass through a shared server, though only they see the incidents they start.
const publicDemo = ["1", "true"].includes(process.env.ARIA_PUBLIC_DEMO ?? "");

export default function NewRunPage() {
  // The open tab and the chosen source live in the address.
  return (
    <Suspense fallback={<LoadingRows rows={6} label="Loading New triage" />}>
      <NewRun publicDemo={publicDemo} />
    </Suspense>
  );
}
