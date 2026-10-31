import type { Metadata } from "next";

import { Guide } from "@/components/console/guide";

export const metadata: Metadata = { title: "Guide" };

export default function GuidePage() {
  return <Guide />;
}
