// The greenhouse palette and type from web/DESIGN.md, at video scale: cream paper, forest ink,
// keylime, mint, sage and slate panels with no shadows, Newsreader for headlines at weight 300,
// Inter for everything else and Geist Mono for log lines and IDs.
import { loadFont } from "@remotion/fonts";
import geistMono from "@fontsource-variable/geist-mono/files/geist-mono-latin-wght-normal.woff2";
import inter from "@fontsource-variable/inter/files/inter-latin-opsz-normal.woff2";
import newsreader from "@fontsource-variable/newsreader/files/newsreader-latin-opsz-normal.woff2";

export const SERIF = "Newsreader";
export const SANS = "Inter";
export const MONO = "Geist Mono";

void loadFont({ family: SERIF, url: newsreader, weight: "200 800" });
void loadFont({ family: SANS, url: inter, weight: "100 900" });
void loadFont({ family: MONO, url: geistMono, weight: "100 900" });

/** Log lines and IDs, with tabular figures. */
export const mono = { fontFamily: MONO, fontFeatureSettings: '"tnum"' } as const;

/** Headlines and statements: the light serif, never bold. */
export const serif = {
  fontFamily: SERIF,
  fontWeight: 300,
  fontOpticalSizing: "auto",
} as const;

export const color = {
  background: "#fffefc", // cream paper
  raised: "#fffefc", // cards, on a panel or ruled on the page
  sunken: "#f2f1eb", // wells: code, bar tracks
  rule: "#efeeeb", // hairlines
  heading: "#0f3e17", // forest ink: headings, links, the main action
  foreground: "#222222", // charcoal body text
  muted: "#3f4a42",
  faint: "#4b564e",
  onForest: "#fffefc", // text on the forest action
  highlight: "#cfe7d3", // mint: the evidence a claim points at
  keylime: "#e1f4df",
  mint: "#cfe7d3",
  sage: "#b1dbb8",
  slate: "#b6ced5",
  danger: "#a3361f",
} as const;

export type Severity = "SEV1" | "SEV2" | "SEV3" | "SEV4";

// Severity keeps its own earthy fills, apart from the greens; labels on them stay in ink.
export const sevColor: Record<Severity, string> = {
  SEV1: "#e9826e",
  SEV2: "#f1aa6a",
  SEV3: "#ead27c",
  SEV4: "#a8c6cf",
};

// The web's scale at video size (1920 x 1080), kept large enough to read on a phone.
export const size = {
  label: 26,
  detail: 30,
  body: 40,
  lead: 50,
  title: 84,
  display: 132,
} as const;

// The web's 14 px card corners and 7 to 10 px small parts, at video scale.
export const radius = { card: 20, small: 12, panel: 20 } as const;

export const SAFE = { x: 140, y: 110 } as const;

/** Small labels: sentence case and medium weight, never uppercase. */
export const labelStyle = {
  fontSize: size.label,
  fontWeight: 500,
  letterSpacing: "-0.005em",
} as const;
