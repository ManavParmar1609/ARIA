import localFont from "next/font/local";

// Atkinson Hyperlegible Next and Mono (SIL OFL 1.1), designed by the Braille Institute so that
// easily confused characters (1 l I, 0 O, rn m) stay distinct: the right faces for reading IDs
// and log lines at three in the morning. Self-hosted from Fontsource, latin subset.
export const atkinson = localFont({
  src: [
    {
      path: "../../node_modules/@fontsource-variable/atkinson-hyperlegible-next/files/atkinson-hyperlegible-next-latin-wght-normal.woff2",
      style: "normal",
    },
    {
      path: "../../node_modules/@fontsource-variable/atkinson-hyperlegible-next/files/atkinson-hyperlegible-next-latin-wght-italic.woff2",
      style: "italic",
    },
  ],
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
  preload: false,
  fallback: ["ui-monospace", "Menlo", "monospace"],
});
