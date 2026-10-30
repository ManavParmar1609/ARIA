import type { Metadata } from "next";

import { Guide } from "@/components/console/guide";

export const metadata: Metadata = { title: "How to use ARIA" };

export default function GuidePage() {
  return <Guide />;
}
