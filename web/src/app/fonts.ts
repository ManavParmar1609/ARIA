import localFont from "next/font/local";

// Atkinson Hyperlegible Next and Mono (SIL OFL 1.1), designed by the Braille Institute so that
// easily confused characters (1 l I, 0 O, rn m) stay distinct: the right faces for reading IDs
// and log lines at three in the morning. Self-hosted from Fontsource, latin subset.

// Upright only: italic is rare here (emphasis in reports), so the browser slants the upright face
// rather than every page preloading a second file.
export const atkinson = localFont({
  src: "../../node_modules/@fontsource-variable/atkinson-hyperlegible-next/files/atkinson-hyperlegible-next-latin-wght-normal.woff2",
  style: "normal",
  weight: "200 800",
  variable: "--font-atkinson",
  display: "swap",
  fallback: ["ui-sans-serif", "system-ui", "sans-serif"],
});

export const atkinsonMono = localFont({
  src: "../../node_modules/@fontsource-variable/atkinson-hyperlegible-mono/files/atkinson-hyperlegible-mono-latin-wght-normal.woff2",
  weight: "200 800",
  variable: "--font-atkinson-mono",
  display: "swap",
  // Preloaded too: log lines sit above the fold on the landing page and the run view, and first
  // paint waits less with the face already on its way. The fallback stays a real monospace face
  // (not metric-adjusted Arial), so a late swap barely moves text.
  fallback: ["ui-monospace", "Menlo", "monospace"],
  adjustFontFallback: false,
});
