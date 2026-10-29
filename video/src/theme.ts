// The web console's night-shift palette (web/src/app/globals.css) and its two faces.
import { loadFont } from "@remotion/fonts";
import mono from "@fontsource-variable/atkinson-hyperlegible-mono/files/atkinson-hyperlegible-mono-latin-wght-normal.woff2";
import sans from "@fontsource-variable/atkinson-hyperlegible-next/files/atkinson-hyperlegible-next-latin-wght-normal.woff2";

export const SANS = "Atkinson Hyperlegible Next";
export const MONO = "Atkinson Hyperlegible Mono";

void loadFont({ family: SANS, url: sans, weight: "200 800" });
void loadFont({ family: MONO, url: mono, weight: "200 800" });

export const color = {
  background: "oklch(0.235 0.03 258)",
  raised: "oklch(0.27 0.032 258)",
  sunken: "oklch(0.205 0.028 258)",
  rule: "oklch(0.37 0.03 258)",
  foreground: "oklch(0.955 0.012 85)",
  muted: "oklch(0.8 0.02 258)",
  faint: "oklch(0.7 0.02 258)",
  manila: "oklch(0.86 0.07 84)",
  highlight: "oklch(0.86 0.07 84 / 0.2)",
  ink: "oklch(0.205 0.028 258)",
  danger: "oklch(0.7 0.19 27)",
  ok: "oklch(0.78 0.1 160)",
} as const;

export type Severity = "SEV1" | "SEV2" | "SEV3" | "SEV4";

export const sevColor: Record<Severity, string> = {
  SEV1: "oklch(0.68 0.2 27)",
  SEV2: "oklch(0.77 0.16 58)",
  SEV3: "oklch(0.87 0.15 98)",
  SEV4: "oklch(0.76 0.06 236)",
};

// A major-third scale at video size (1920 x 1080), kept large enough to read on a phone.
export const size = {
  detail: 30,
  body: 40,
  lead: 52,
  title: 76,
  display: 116,
} as const;

export const SAFE = { x: 140, y: 110 } as const;
