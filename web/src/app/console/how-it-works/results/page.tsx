import type { Metadata } from "next";

import { ResultsPart } from "@/components/site/story";

export const metadata: Metadata = { title: "How ARIA works: test results" };

export default function ResultsPage() {
  return <ResultsPart />;
}
