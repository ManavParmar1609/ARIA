import { AbsoluteFill, useCurrentFrame } from "remotion";

import { Label, Lead } from "../components";
import { REPO } from "../data";
import { enter, progress } from "../motion";
import { Orb } from "../orb";
import { MONO, SAFE, SANS, color, gradient, radius, size } from "../theme";

/** Where to get it: the promise again, and the one call to action in aurora. */
export const Close = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill
      style={{ backgroundColor: color.background, color: color.foreground, fontFamily: SANS }}
    >
      <Orb
        size={900}
        style={{ position: "absolute", right: -80, top: 90, opacity: 0.9 * progress(frame, 0, 30) }}
      />
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
            letterSpacing: "-0.046em",
            lineHeight: 1,
            color: color.heading,
            maxWidth: 1000,
            ...enter(frame, 6),
          }}
        >
          Open source, and offline by default.
        </div>
        <Lead style={{ maxWidth: 940, ...enter(frame, 18) }}>
          Add an NVIDIA NIM key and the agents write with open models; Azure OpenAI and any
          OpenAI-compatible server are a config change away.
        </Lead>
        <div
          style={{
            alignSelf: "flex-start",
            backgroundImage: gradient.aurora,
            color: color.ink,
            borderRadius: radius.small,
            padding: "18px 30px",
            fontFamily: MONO,
            fontSize: 38,
            ...enter(frame, 32),
          }}
        >
          {REPO}
        </div>
      </div>
    </AbsoluteFill>
  );
};
