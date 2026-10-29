import { useCurrentFrame } from "remotion";

import { Lead, Stage } from "../components";
import { REPO } from "../data";
import { enter } from "../motion";
import { MONO, color, size } from "../theme";

export const Close = () => {
  const frame = useCurrentFrame();
  return (
    <Stage>
      <div
        style={{
          marginTop: "auto",
          marginBottom: "auto",
          display: "flex",
          flexDirection: "column",
          gap: 40,
        }}
      >
        <div
          style={{
            fontSize: size.display,
            fontWeight: 800,
            letterSpacing: "-0.03em",
            lineHeight: 1.02,
            ...enter(frame, 0),
          }}
        >
          Open source, and offline by default.
        </div>
        <Lead style={{ maxWidth: 1400, ...enter(frame, 14) }}>
          Add an NVIDIA NIM key and the agents write with open models; Azure OpenAI and any
          OpenAI-compatible server are a config change away.
        </Lead>
        <div
          style={{
            fontFamily: MONO,
            fontSize: size.lead,
            color: color.manila,
            ...enter(frame, 30),
          }}
        >
          {REPO}
        </div>
      </div>
    </Stage>
  );
};
