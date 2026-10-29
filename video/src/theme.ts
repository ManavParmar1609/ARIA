// The Auros palette and faces from web/DESIGN.md, at video scale: an abyssal teal surface stack,
// Geist at weight 500 with tight tracking, lavender for large statistics, and the aurora gradient
// for the one call to action.
import { loadFont } from "@remotion/fonts";
import mono from "@fontsource-variable/geist-mono/files/geist-mono-latin-wght-normal.woff2";
import sans from "@fontsource-variable/geist/files/geist-latin-wght-normal.woff2";

export const SANS = "Geist";
export const MONO = "Geist Mono";

void loadFont({ family: SANS, url: sans, weight: "100 900" });
void loadFont({ family: MONO, url: mono, weight: "100 900" });

export const color = {
  background: "#012624", // liquid abyss
  raised: "#003734", // liquid kelp
  sunken: "#011d1c", // liquid deep
  rule: "rgba(255, 255, 255, 0.1)",
  heading: "#ffffff",
  foreground: "#edfffe", // liquid mist
  muted: "#bbc7c6", // silver mist
  faint: "#93a3a2",
  accent: "#cbfffc", // aqua, the aurora's first stop
  highlight: "rgba(203, 255, 252, 0.16)",
  stat: "#fde9ff", // lavender phosphor
  teal: "#00827c",
  ink: "#011d1c",
  danger: "oklch(0.8 0.13 18)",
  ok: "oklch(0.86 0.1 175)",
} as const;

export const gradient = {
  aurora: "linear-gradient(90deg, #cbfffc 0%, #edfffe 26.25%, #fffdfa 47.57%, #fad1ff 88.96%)",
  bio: "linear-gradient(90deg, #00827c 0%, #cbfffc 100%)",
} as const;

export type Severity = "SEV1" | "SEV2" | "SEV3" | "SEV4";

// The four severity strips, tuned to sit inside the aurora palette; labels stay in dark ink.
export const sevColor: Record<Severity, string> = {
  SEV1: "oklch(0.74 0.15 18)",
  SEV2: "oklch(0.83 0.12 68)",
  SEV3: "oklch(0.91 0.1 100)",
  SEV4: "oklch(0.85 0.05 195)",
};

// A major-third scale at video size (1920 x 1080), kept large enough to read on a phone.
export const size = {
  label: 24,
  detail: 30,
  body: 40,
  lead: 50,
  title: 80,
  display: 124,
} as const;

// Two radii, scaled from the web's 16 and 6 px to the video's 1920 px frame.
export const radius = { card: 24, small: 8 } as const;

export const SAFE = { x: 140, y: 110 } as const;

/** Uppercase instrument labels: section kickers, the rail, small captions. */
export const labelStyle = {
  fontSize: size.label,
  fontWeight: 500,
  letterSpacing: "0.12em",
  textTransform: "uppercase",
} as const;
