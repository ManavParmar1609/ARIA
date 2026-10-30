import type { Metadata } from "next";

import { Ask } from "@/components/console/ask";

export const metadata: Metadata = { title: "Ask ARIA" };

export default function AskPage() {
  return <Ask />;
}
