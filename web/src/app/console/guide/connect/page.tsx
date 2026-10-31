import type { Metadata } from "next";

import { Connect } from "@/components/console/connect";

export const metadata: Metadata = { title: "Connect ARIA to your systems" };

export default function ConnectPage() {
  return <Connect />;
}
