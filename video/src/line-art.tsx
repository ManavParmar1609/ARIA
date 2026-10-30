import type { CSSProperties } from "react";
import { useCurrentFrame } from "remotion";

import { progress } from "./motion";

/** Where each line starts before it bends: uneven, like log lines (web/src/components/site/line-art.tsx). */
const START = [52, 18, 70, 6, 40, 0, 62, 26, 46];

/**
 * The landing page's line drawing: loose lines that run together into one, the logs becoming one
 * incident. Each stroke draws in from frame `start`, a little after the one before.
 */
export const Converge = ({
  start = 0,
  stroke,
  style,
}: {
  start?: number;
  stroke: string;
  style?: CSSProperties;
}) => {
  const frame = useCurrentFrame();
  const mid = 120;
  const drawn = (i: number) => 1 - progress(frame, start + i * 4, 46);
  return (
    // Drawn at its own aspect ratio, so the normalised path length matches what the stroke covers.
    <svg viewBox="0 0 1200 240" style={{ display: "block", ...style }}>
      <g fill="none" stroke={stroke} strokeWidth={2.5} strokeLinecap="round">
        {START.map((x0, i) => {
          const y = 40 + i * 20;
          return (
            <path
              key={i}
              d={`M${x0} ${y}H640C760 ${y} 820 ${mid} 940 ${mid}`}
              pathLength={1}
              strokeDasharray={1}
              strokeDashoffset={drawn(i)}
            />
          );
        })}
        <path
          d={`M940 ${mid}H1200`}
          pathLength={1}
          strokeDasharray={1}
          strokeDashoffset={drawn(START.length)}
        />
      </g>
    </svg>
  );
};
