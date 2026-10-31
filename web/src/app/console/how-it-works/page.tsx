import type { Metadata } from "next";

import { WhatItDoesPart } from "@/components/site/story";

export const metadata: Metadata = { title: "How ARIA works" };

export default function WhatItDoesPage() {
  return <WhatItDoesPart />;
}
