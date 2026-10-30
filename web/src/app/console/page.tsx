import type { Metadata } from "next";

import { Overview } from "@/components/console/overview";

// The console layout's "%s | ARIA console" reaches only its child pages, not this one.
export const metadata: Metadata = { title: { absolute: "Overview | ARIA console" } };

export default function OverviewPage() {
  return <Overview />;
}
