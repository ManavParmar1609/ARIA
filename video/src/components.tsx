import type { CSSProperties, ReactNode } from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";

import { enter, FADE } from "./motion";
import {
  mono,
  SAFE,
  SANS,
  color,
  labelStyle,
  radius,
  sevColor,
  size,
  type Severity,
} from "./theme";

/** A full frame of cream paper, with the safe area as padding. */
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
        fontWeight: 500,
        letterSpacing: "-0.04em",
        lineHeight: 1.02,
        color: color.heading,
        maxWidth: 1640,
        // A scene starts while the last one is still fading out; its title waits for most of
        // the fade, so two titles never sit on top of each other.
        ...enter(frame, FADE - 3),
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

/** A white card on the cream page: depth from the paper stack, never a border or a shadow. */
export const Panel = ({ children, style }: { children: ReactNode; style?: CSSProperties }) => (
  <div
    style={{
      backgroundColor: color.raised,
      borderRadius: radius.card,
      padding: 36,
      ...style,
    }}
  >
    {children}
  </div>
);

/** A small sentence-case label with a grass dot; it names what follows. */
export const Label = ({ children, style }: { children: ReactNode; style?: CSSProperties }) => (
  <div
    style={{
      ...labelStyle,
      color: color.muted,
      display: "flex",
      alignItems: "center",
      gap: 14,
      ...style,
    }}
  >
    <span
      style={{
        width: 16,
        height: 16,
        borderRadius: 8,
        backgroundColor: color.grass,
        boxSizing: "border-box",
        border: `2px solid ${color.ink}`,
      }}
    />
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
      fontWeight: 500,
      fontSize: 34 * scale,
      padding: `${6 * scale}px ${16 * scale}px`,
      borderRadius: radius.small,
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
      ...mono,
      fontSize: 28,
      padding: "2px 10px",
      marginLeft: 10,
      borderRadius: radius.small,
      border: `2px solid ${lit ? color.ink : color.faint}`,
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
export const Rail = ({ active }: { active: Step }) => {
  const at = STEPS.indexOf(active);
  return (
    <div style={{ marginTop: "auto", display: "flex", gap: 12 }}>
      {STEPS.map((step, i) => {
        const on = step === active;
        return (
          <div
            key={step}
            style={{
              flex: 1,
              borderTop: `4px solid ${on ? color.accent : i < at ? color.teal : color.rule}`,
              paddingTop: 16,
              ...labelStyle,
              color: on ? color.heading : color.faint,
            }}
          >
            {i + 1} {step}
          </div>
        );
      })}
    </div>
  );
};
