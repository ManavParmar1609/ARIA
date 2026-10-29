import { AbsoluteFill, useCurrentFrame } from "remotion";

import { Label, Lead } from "../components";
import { run } from "../data";
import { enter, progress } from "../motion";
import { Orb } from "../orb";
import { SAFE, SANS, color, size } from "../theme";

/** The landing page's hero: the orb rising behind the promise. */
export const Opening = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill
      style={{ backgroundColor: color.background, color: color.foreground, fontFamily: SANS }}
    >
      <Orb
        size={1000}
        style={{
          position: "absolute",
          left: 460,
          top: -150,
          opacity: progress(frame, 0, 45),
          maskImage: "linear-gradient(to bottom, #000 36%, transparent 64%)",
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          padding: `${SAFE.y}px ${SAFE.x}px`,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "flex-end",
          textAlign: "center",
          gap: 30,
        }}
      >
        <Label style={enter(frame, 10)}>Open-source incident triage</Label>
        <h1
          style={{
            margin: 0,
            fontSize: size.display,
            fontWeight: 500,
            letterSpacing: "-0.046em",
            lineHeight: 1,
            color: color.heading,
            maxWidth: 1500,
            ...enter(frame, 16, 32),
          }}
        >
          Incident triage that shows its work.
        </h1>
        <Lead style={{ maxWidth: 1260, ...enter(frame, 28) }}>
          It reads the logs, rates severity, finds similar incidents and drafts a report in which
          every claim cites evidence. A person approves it.
        </Lead>
        <p
          style={{
            margin: 0,
            marginTop: 20,
            fontSize: 28,
            color: color.faint,
            ...enter(frame, 44),
          }}
        >
          A recorded ARIA run.{" "}
          {run.synthetic
            ? "The incident is semi-synthetic: real Loghub lines, composed by ARIA's scenario builder."
            : ""}
        </p>
      </div>
    </AbsoluteFill>
  );
};
