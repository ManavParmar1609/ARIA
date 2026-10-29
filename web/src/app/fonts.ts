import localFont from "next/font/local";

// Inter (SIL OFL 1.1), self-hosted from Fontsource, latin subset. The style reference uses Inter
// alone, at weights 400 and 500 (DESIGN.md). This file carries the optical-size axis as well as
// weight, so the 144 px display headline gets Inter's display cut and body text its text cut.
// Code and log lines use the same face with its disambiguation set (see globals.css), so there
// is no second typeface to download.

export const inter = localFont({
  src: "../../node_modules/@fontsource-variable/inter/files/inter-latin-opsz-normal.woff2",
  style: "normal",
  weight: "100 900",
  variable: "--font-inter",
  display: "swap",
  fallback: ["ui-sans-serif", "system-ui", "sans-serif"],
});
