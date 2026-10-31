import type { Metadata } from "next";

import { Memory } from "@/components/console/memory";

export const metadata: Metadata = { title: "Incident library" };

export default function MemoryPage() {
  return <Memory />;
}
