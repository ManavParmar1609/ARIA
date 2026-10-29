import type { Metadata } from "next";

import { Memory } from "@/components/console/memory";

export const metadata: Metadata = { title: "Incident memory" };

export default function MemoryPage() {
  return <Memory />;
}
