import { AbsoluteFill, useCurrentFrame } from "remotion";

import { Label, Lead } from "../components";
import { REPO } from "../data";
import { Converge } from "../line-art";
import { enter } from "../motion";
import { SAFE, SANS, color, mono, radius, serif, size } from "../theme";

/** Where to get it: the closing panel from the landing page, its lines running into one. */
export const Close = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ backgroundColor: color.background, fontFamily: SANS, padding: 48 }}>
      <div
        style={{
          position: "relative",
          height: "100%",
          backgroundColor: color.sage,
          borderRadius: radius.panel,
          padding: `${SAFE.y - 30}px ${SAFE.x - 40}px`,
          display: "flex",
          flexDirection: "column",
          gap: 36,
          overflow: "hidden",
        }}
      >
        <Label style={{ backgroundColor: color.raised, ...enter(frame, 0) }}>Try it</Label>
        <div
          style={{
            ...serif,
            fontSize: size.display,
            letterSpacing: "-0.03em",
            lineHeight: 1,
            color: color.heading,
            maxWidth: 1300,
            ...enter(frame, 6),
          }}
        >
          Let ARIA take the first look.
        </div>
        <Lead style={{ color: color.heading, maxWidth: 1100, ...enter(frame, 18) }}>
          It runs offline with no API key, and switches to Gemini, NVIDIA NIM, Azure OpenAI or any
          OpenAI-compatible model when you add one.
        </Lead>
        <div
          style={{
            alignSelf: "flex-start",
            display: "flex",
            alignItems: "center",
            gap: 22,
            backgroundColor: color.heading,
            color: color.onForest,
            borderRadius: radius.small,
            padding: "14px 14px 14px 30px",
            fontSize: 36,
            ...mono,
            ...enter(frame, 32),
          }}
        >
          {REPO}
          <svg width={52} height={52} viewBox="0 0 24 24" fill="none">
            <path
              d="M5 12h14M13 6l6 6-6 6"
              stroke={color.onForest}
              strokeWidth={1.75}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </div>
        <Converge
          start={20}
          stroke={color.heading}
          style={{ position: "absolute", right: 60, bottom: 50, width: 1000, height: "auto" }}
        />
      </div>
    </AbsoluteFill>
  );
};
