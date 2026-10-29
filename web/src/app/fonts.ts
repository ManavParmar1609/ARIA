import localFont from "next/font/local";

// Geist and Geist Mono (SIL OFL 1.1), self-hosted from Fontsource, latin subset. The Auros style
// reference specifies Matter, a commercial face; Geist is the closest open match, a geometric
// grotesque with the same engineered confidence at weight 500 with tight tracking (DESIGN.md).

export const geist = localFont({
  src: "../../node_modules/@fontsource-variable/geist/files/geist-latin-wght-normal.woff2",
  style: "normal",
  weight: "100 900",
  variable: "--font-geist",
  display: "swap",
  fallback: ["ui-sans-serif", "system-ui", "sans-serif"],
});

export const geistMono = localFont({
  src: "../../node_modules/@fontsource-variable/geist-mono/files/geist-mono-latin-wght-normal.woff2",
  weight: "100 900",
  variable: "--font-geist-mono",
  display: "swap",
  // Not preloaded: on the landing page monospace text starts below the fold, and on a slow
  // connection the preload would compete with what the first screen needs. The fallback is a real
  // monospace face, so the late swap barely moves text.
  preload: false,
  fallback: ["ui-monospace", "Menlo", "monospace"],
  adjustFontFallback: false,
});
