import type { Metadata } from "next";

import { Overview } from "@/components/console/overview";

export const metadata: Metadata = { title: "Overview" };

export default function OverviewPage() {
  return <Overview />;
}
