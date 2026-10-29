import type { Metadata } from "next";

import { NewRun } from "@/components/console/new-run";

export const metadata: Metadata = { title: "New triage" };

export default function NewRunPage() {
  return <NewRun />;
}
