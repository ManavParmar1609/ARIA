// The cream-paper palette and Inter from web/DESIGN.md, at video scale: cream page, white cards,
// sandstone wells, ink text, grass panels and accents, and the four decorative pops.
import { loadFont } from "@remotion/fonts";
import inter from "@fontsource-variable/inter/files/inter-latin-opsz-normal.woff2";

export const SANS = "Inter";
// Code and log lines use Inter too, with its disambiguation set (see `mono` below).
export const MONO = "Inter";

void loadFont({ family: SANS, url: inter, weight: "100 900" });

/** Slashed zero, serifed I, l with a tail, and tabular figures, for log lines and IDs. */
export const mono = { fontFamily: MONO, fontFeatureSettings: '"ss02", "tnum"' } as const;

export const color = {
  background: "#f5f1e4", // cream paper
  raised: "#ffffff", // cards
  sunken: "#e0dbce", // sandstone wells
  rule: "#d5d5d4", // hairline mist
  heading: "#2c2e2a", // ink
  foreground: "#2c2e2a",
  muted: "#50524e",
  faint: "#5d5f5a",
  accent: "#8ed462", // fresh grass
  highlight: "#8ed462",
  stat: "#2c2e2a",
  teal: "#6fbf3f", // deeper grass, for steps already done
  ink: "#2c2e2a",
  danger: "oklch(0.5 0.18 25)",
  ok: "oklch(0.47 0.11 145)",
  grass: "#8ed462",
  sky: "#2ba0ff",
  coral: "#ff705d",
  sunshine: "#f5e211",
  lilac: "#ebc0ff",
} as const;

export type Severity = "SEV1" | "SEV2" | "SEV3" | "SEV4";

// The four severity strips: their own hues, kept apart from the pops; labels stay in ink.
export const sevColor: Record<Severity, string> = {
  SEV1: "oklch(0.72 0.15 15)",
  SEV2: "oklch(0.8 0.14 60)",
  SEV3: "oklch(0.87 0.13 95)",
  SEV4: "oklch(0.83 0.04 235)",
};

// The web's scale at video size (1920 x 1080), kept large enough to read on a phone.
export const size = {
  label: 26,
  detail: 30,
  body: 40,
  lead: 50,
  title: 84,
  display: 150,
} as const;

// Crisp corners on cards and chips, 70 px only on whole panels (the web's 8, 6 and 50 px).
export const radius = { card: 14, small: 10, sheet: 70 } as const;

export const SAFE = { x: 140, y: 110 } as const;

/** Small labels: sentence case and medium weight, never uppercase. */
export const labelStyle = {
  fontSize: size.label,
  fontWeight: 500,
  letterSpacing: "-0.005em",
} as const;
