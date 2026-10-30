import localFont from "next/font/local";

// Three faces, all SIL OFL 1.1 and self-hosted from Fontsource (latin subset, variable): Newsreader
// sets headlines at weight 300 (the style reference's light display serif), Inter sets the
// interface and running text, and Geist Mono sets log lines, IDs and commands (DESIGN.md). The
// Newsreader and Inter files carry the optical-size axis, so large headlines get the display cut.

export const newsreader = localFont({
  src: "../../node_modules/@fontsource-variable/newsreader/files/newsreader-latin-opsz-normal.woff2",
  style: "normal",
  weight: "200 800",
  variable: "--font-newsreader",
  display: "swap",
  fallback: ["Georgia", "ui-serif", "serif"],
});

export const inter = localFont({
  src: "../../node_modules/@fontsource-variable/inter/files/inter-latin-opsz-normal.woff2",
  style: "normal",
  weight: "100 900",
  variable: "--font-inter",
  display: "swap",
  fallback: ["ui-sans-serif", "system-ui", "sans-serif"],
});

// Log lines appear below the fold on the landing page, so the mono face is not preloaded.
export const geistMono = localFont({
  src: "../../node_modules/@fontsource-variable/geist-mono/files/geist-mono-latin-wght-normal.woff2",
  style: "normal",
  weight: "100 900",
  variable: "--font-geist-mono",
  display: "swap",
  preload: false,
  fallback: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
});
