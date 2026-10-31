import type { Metadata } from "next";

import { StepsPart } from "@/components/site/story";

export const metadata: Metadata = { title: "How ARIA works: the four steps" };

export default function StepsPage() {
  return <StepsPart />;
}
