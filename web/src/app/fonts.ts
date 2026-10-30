import localFont from "next/font/local";

// Three faces, all SIL OFL 1.1 and self-hosted from Fontsource (latin subset, variable): Newsreader
// sets headlines at weight 300 (the style reference's light display serif), Inter sets the
// interface and running text, and Geist Mono sets log lines, IDs and commands (DESIGN.md). The
// two preloaded faces sit on the phone landing page's critical path (the hero headline is its
// largest paint), so both load the weight-only files: the optical-size files are more than twice
// the size, and at these sizes the difference is barely visible.

export const newsreader = localFont({
  src: "../../node_modules/@fontsource-variable/newsreader/files/newsreader-latin-wght-normal.woff2",
  style: "normal",
  weight: "200 800",
  variable: "--font-newsreader",
  display: "swap",
  // A metric-matched serif stands in while the face loads, so the headline neither changes style
  // nor jumps when it swaps.
  adjustFontFallback: "Times New Roman",
  fallback: ["Georgia", "ui-serif", "serif"],
});

export const inter = localFont({
  src: "../../node_modules/@fontsource-variable/inter/files/inter-latin-wght-normal.woff2",
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
  // Its fallbacks are monospaced too; metrics from a proportional face would only distort them.
  adjustFontFallback: false,
  fallback: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
});
