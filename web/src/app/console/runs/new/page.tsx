import type { Metadata } from "next";

import { NewRun } from "@/components/console/new-run";

export const metadata: Metadata = { title: "New triage" };

// A public demo (ARIA_PUBLIC_DEMO=1, read when the page is built) warns that every visitor can
// open the runs on it.
const publicDemo = ["1", "true"].includes(process.env.ARIA_PUBLIC_DEMO ?? "");

export default function NewRunPage() {
  return <NewRun publicDemo={publicDemo} />;
}
