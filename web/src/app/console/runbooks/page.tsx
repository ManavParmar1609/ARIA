import type { Metadata } from "next";

import { Runbooks } from "@/components/console/runbooks";

export const metadata: Metadata = { title: "Runbooks" };

export default function RunbooksPage() {
  return <Runbooks />;
}
