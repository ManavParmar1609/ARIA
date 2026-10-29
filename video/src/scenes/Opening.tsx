import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";

import { HeroScene } from "../../../web/src/components/illustrations/scenes";
import { run } from "../data";
import { enter, progress } from "../motion";
import { SAFE, SANS, color, size } from "../theme";

/** The landing page's hero: the promise on a green panel, the crew riding in beneath it. */
export const Opening = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const arrive = progress(frame, 8, 40);
  return (
    <AbsoluteFill style={{ backgroundColor: color.grass, color: color.ink, fontFamily: SANS }}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          padding: `${SAFE.y - 30}px ${SAFE.x}px`,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          textAlign: "center",
          gap: 26,
        }}
      >
        <h1
          style={{
            margin: 0,
            fontSize: size.display,
            fontWeight: 500,
            letterSpacing: "-0.06em",
            lineHeight: 0.95,
            maxWidth: 1500,
            ...enter(frame, 4, 36),
          }}
        >
          Incident triage that shows its work.
        </h1>
        <p
          style={{
            margin: 0,
            fontSize: 46,
            fontWeight: 500,
            letterSpacing: "-0.03em",
            lineHeight: 1.2,
            maxWidth: 1180,
            ...enter(frame, 18),
          }}
        >
          Calibrated severity, a report that cites every claim, and nothing sent until a person
          approves.
        </p>
        <p style={{ margin: 0, fontSize: 28, ...enter(frame, 34) }}>
          A recorded ARIA run.{" "}
          {run.synthetic
            ? "The incident is semi-synthetic: real Loghub lines, composed by ARIA's scenario builder."
            : ""}
        </p>
      </div>
      <div
        style={{
          position: "absolute",
          left: 360,
          right: 360,
          bottom: -90,
          opacity: arrive,
          translate: `${(1 - arrive) * -120}px ${(1 - arrive) * 60}px`,
        }}
      >
        <HeroScene t={frame / fps} />
      </div>
    </AbsoluteFill>
  );
};
