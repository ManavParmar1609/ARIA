import type { Metadata } from "next";

import { ExamplePart } from "@/components/site/story";

export const metadata: Metadata = { title: "How ARIA works: an example" };

export default function ExamplePage() {
  return <ExamplePart />;
}
