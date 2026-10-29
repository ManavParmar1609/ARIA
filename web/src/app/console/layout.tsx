import type { Metadata } from "next";
import { type ReactNode } from "react";

import { DataProviders } from "@/components/console/data-providers";
import { ConsoleShell } from "@/components/console/shell";

export const metadata: Metadata = {
  title: { default: "Console", template: "%s | ARIA console" },
  robots: { index: false, follow: false },
};

export default function ConsoleLayout({ children }: { children: ReactNode }) {
  return (
    <DataProviders>
      <ConsoleShell>{children}</ConsoleShell>
    </DataProviders>
  );
}
