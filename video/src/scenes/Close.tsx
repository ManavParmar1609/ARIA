import { AbsoluteFill, useCurrentFrame } from "remotion";

import { ApproveScene } from "../../../web/src/components/illustrations/scenes";
import { Label, Lead } from "../components";
import { REPO } from "../data";
import { enter, progress } from "../motion";
import { SAFE, SANS, color, mono, radius, size } from "../theme";

/** Where to get it: the promise again, a thumbs-up, and the message flying once approved. */
export const Close = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill
      style={{ backgroundColor: color.background, color: color.foreground, fontFamily: SANS }}
    >
      <div style={{ position: "absolute", right: 60, top: 150, width: 860, ...enter(frame, 4) }}>
        <ApproveScene planeAt={progress(frame, 40, 70)} />
      </div>
      <div
        style={{
          position: "absolute",
          inset: 0,
          padding: `${SAFE.y}px ${SAFE.x}px`,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          gap: 40,
        }}
      >
        <Label style={enter(frame, 0)}>Try it</Label>
        <div
          style={{
            fontSize: size.display,
            fontWeight: 500,
            letterSpacing: "-0.06em",
            lineHeight: 0.95,
            color: color.heading,
            maxWidth: 980,
            ...enter(frame, 6),
          }}
        >
          Open source, and offline by default.
        </div>
        <Lead style={{ maxWidth: 900, ...enter(frame, 18) }}>
          Add an NVIDIA NIM key and the agents write with open models; Azure OpenAI and any
          OpenAI-compatible server are a config change away.
        </Lead>
        <div
          style={{
            alignSelf: "flex-start",
            display: "flex",
            alignItems: "center",
            gap: 22,
            backgroundColor: color.grass,
            color: color.ink,
            borderRadius: radius.small,
            padding: "14px 14px 14px 30px",
            fontSize: 38,
            ...mono,
            ...enter(frame, 32),
          }}
        >
          {REPO}
          <span
            style={{
              width: 56,
              height: 56,
              borderRadius: 28,
              backgroundColor: "#ffffff",
              display: "grid",
              placeItems: "center",
              fontFamily: SANS,
              fontSize: 34,
            }}
          >
            ›
          </span>
        </div>
      </div>
    </AbsoluteFill>
  );
};
