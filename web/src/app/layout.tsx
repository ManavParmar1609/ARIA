import type { Metadata, Viewport } from "next";
import { type ReactNode } from "react";

import { HashLinks } from "@/components/hash-links";
import { THEME_SCRIPT } from "@/lib/theme-script";

import { geistMono, inter, newsreader } from "./fonts";
import "./globals.css";

// Where the site is published: ARIA_WEB_URL, else the address Vercel gives the production
// deployment, else a local run. Read at build time (pages are prerendered); empty values fall back.
const vercel = process.env.VERCEL_PROJECT_PRODUCTION_URL;
const siteUrl =
  process.env.ARIA_WEB_URL || (vercel ? `https://${vercel}` : "http://localhost:3000");

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: "ARIA: incident triage that shows its work",
    template: "%s | ARIA",
  },
  description:
    "ARIA reads the alert and the logs, rates severity with calibrated confidence, finds similar past incidents and drafts a report in which every claim cites its evidence. Nothing is sent until a person approves.",
  applicationName: "ARIA",
  openGraph: { type: "website", siteName: "ARIA" },
  twitter: { card: "summary_large_image" },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fffefc" },
    { media: "(prefers-color-scheme: dark)", color: "#0f1a13" },
  ],
  colorScheme: "light dark",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en"
      className={`${newsreader.variable} ${inter.variable} ${geistMono.variable}`}
      suppressHydrationWarning
    >
      <head>
        {/* Before first paint: apply the stored theme, and mark that script runs so animated
            elements can start hidden. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `document.documentElement.classList.add('js');${THEME_SCRIPT}`,
          }}
        />
      </head>
      <body>
        {children}
        <HashLinks />
      </body>
    </html>
  );
}
