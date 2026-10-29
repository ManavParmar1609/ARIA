import type { Metadata, Viewport } from "next";
import { type ReactNode } from "react";

import { Providers } from "@/components/providers";

import { atkinson, atkinsonMono } from "./fonts";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.ARIA_WEB_URL ?? "http://localhost:3000"),
  title: {
    default: "ARIA: incident triage that shows its work",
    template: "%s | ARIA",
  },
  description:
    "ARIA reads the alert and the logs, rates severity with calibrated confidence, finds similar past incidents and drafts a report in which every claim cites its evidence. Nothing is sent until a person approves.",
  applicationName: "ARIA",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#151e2c" },
    { media: "(prefers-color-scheme: light)", color: "#f5f7fa" },
  ],
  colorScheme: "dark light",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en"
      className={`dark ${atkinson.variable} ${atkinsonMono.variable}`}
      suppressHydrationWarning
    >
      <head>
        {/* Marks that script runs, before first paint, so animated elements can start hidden. */}
        <script
          dangerouslySetInnerHTML={{ __html: "document.documentElement.classList.add('js')" }}
        />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
