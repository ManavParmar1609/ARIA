import type { Metadata } from "next";

import { Evals } from "@/components/console/evals";
import { evaluation } from "@/lib/site-data";

export const metadata: Metadata = { title: "Evaluation" };

export default function EvalsPage() {
  return <Evals data={evaluation()} />;
}
