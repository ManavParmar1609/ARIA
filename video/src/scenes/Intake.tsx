import { useCurrentFrame } from "remotion";

import { Heading, Rail, Stage } from "../components";
import { run } from "../data";
import { enter, progress } from "../motion";
import { MONO, color, size } from "../theme";

const ROW_EVERY = 10; // frames between rows

/** Lines stream into the log well; one of them is an instruction, and ARIA quarantines it. */
export const Intake = () => {
  const frame = useCurrentFrame();
  const plantedRow = Math.max(
    0,
    run.well.findIndex((row) => row.planted),
  );
  const flagged = progress(frame, 18 + (plantedRow + 3) * ROW_EVERY, 18);
  return (
    <Stage>
      <Heading>
        {run.lines} lines from {run.system} arrive in {run.span}.
      </Heading>
      <div
        style={{
          backgroundColor: color.sunken,
          border: `2px solid ${color.rule}`,
          borderRadius: 6,
          padding: "24px 32px",
          display: "flex",
          flexDirection: "column",
          gap: 8,
          fontFamily: MONO,
          fontSize: 28,
          overflow: "hidden",
        }}
      >
        {run.well.map((row, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              gap: 24,
              whiteSpace: "nowrap",
              padding: "4px 12px",
              borderRadius: 4,
              outline: row.planted ? `3px solid oklch(0.7 0.19 27 / ${flagged})` : "none",
              backgroundColor: row.planted
                ? `oklch(0.7 0.19 27 / ${0.16 * flagged})`
                : "transparent",
              ...enter(frame, 18 + i * ROW_EVERY, 12),
            }}
          >
            <span style={{ color: color.faint }}>{row.time}</span>
            <span
              style={{
                color: row.level === "WARN" ? "oklch(0.78 0.15 58)" : color.faint,
                width: 64,
              }}
            >
              {row.level}
            </span>
            <span style={{ color: row.planted ? color.foreground : color.muted }}>{row.text}</span>
          </div>
        ))}
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 28,
          opacity: flagged,
          translate: `0px ${(1 - flagged) * 20}px`,
        }}
      >
        <span
          style={{
            backgroundColor: color.danger,
            color: color.ink,
            fontWeight: 800,
            fontSize: size.body,
            padding: "4px 18px",
            borderRadius: 2,
          }}
        >
          Quarantined
        </span>
        <span style={{ fontSize: size.body }}>
          An instruction, not a log: reviewers see it, the analysis never does.
        </span>
      </div>
      <Rail active="Intake" />
    </Stage>
  );
};
