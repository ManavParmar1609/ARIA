import type { CSSProperties, ReactNode } from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";

import { enter } from "./motion";
import { MONO, SAFE, SANS, color, sevColor, size, type Severity } from "./theme";

/** A full frame on the night-shift background, with the safe area as padding. */
export const Stage = ({ children }: { children: ReactNode }) => (
  <AbsoluteFill
    style={{
      backgroundColor: color.background,
      color: color.foreground,
      fontFamily: SANS,
      padding: `${SAFE.y}px ${SAFE.x}px`,
      display: "flex",
      flexDirection: "column",
      gap: 36,
    }}
  >
    {children}
  </AbsoluteFill>
);

/** The scene's one sentence, entering first. */
export const Heading = ({ children }: { children: ReactNode }) => {
  const frame = useCurrentFrame();
  return (
    <h1
      style={{
        margin: 0,
        fontSize: size.title,
        fontWeight: 800,
        letterSpacing: "-0.03em",
        lineHeight: 1.05,
        maxWidth: 1640,
        ...enter(frame, 0),
      }}
    >
      {children}
    </h1>
  );
};

/** Lines of supporting text, muted. */
export const Lead = ({ children, style }: { children: ReactNode; style?: CSSProperties }) => (
  <p style={{ margin: 0, fontSize: size.lead, lineHeight: 1.25, color: color.muted, ...style }}>
    {children}
  </p>
);

/** A raised panel; the console's panels and tags share it. */
export const Panel = ({ children, style }: { children: ReactNode; style?: CSSProperties }) => (
  <div
    style={{
      backgroundColor: color.raised,
      border: `2px solid ${color.rule}`,
      borderRadius: 6,
      padding: 32,
      ...style,
    }}
  >
    {children}
  </div>
);

/** A severity label on its strip colour, always in dark ink so colour is never the only cue. */
export const SevBadge = ({ severity, scale = 1 }: { severity: Severity; scale?: number }) => (
  <span
    style={{
      display: "inline-block",
      backgroundColor: sevColor[severity],
      color: color.ink,
      fontWeight: 800,
      fontSize: 34 * scale,
      padding: `${6 * scale}px ${16 * scale}px`,
      borderRadius: 2,
      fontVariantNumeric: "tabular-nums",
    }}
  >
    {severity}
  </span>
);

/** An evidence ID, as the console shows citations. */
export const Chip = ({ id, lit = false }: { id: string; lit?: boolean }) => (
  <span
    style={{
      display: "inline-block",
      fontFamily: MONO,
      fontSize: 28,
      padding: "2px 10px",
      marginLeft: 10,
      borderRadius: 4,
      border: `2px solid ${lit ? color.manila : color.rule}`,
      backgroundColor: lit ? color.highlight : "transparent",
      color: lit ? color.foreground : color.muted,
      verticalAlign: "middle",
    }}
  >
    {id}
  </span>
);

const STEPS = ["Intake", "Parse", "Severity", "Investigate", "Report", "Review"] as const;
export type Step = (typeof STEPS)[number];

/** Where the run is in the pipeline: the steps really are a sequence, so they are numbered. */
export const Rail = ({ active }: { active: Step }) => (
  <div style={{ marginTop: "auto", display: "flex", gap: 12 }}>
    {STEPS.map((step, i) => {
      const on = step === active;
      return (
        <div
          key={step}
          style={{
            flex: 1,
            borderTop: `6px solid ${on ? color.manila : color.rule}`,
            paddingTop: 14,
            fontSize: 30,
            fontWeight: on ? 800 : 400,
            color: on ? color.foreground : color.faint,
          }}
        >
          {i + 1}. {step}
        </div>
      );
    })}
  </div>
);
