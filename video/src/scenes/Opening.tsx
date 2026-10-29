import { useCurrentFrame } from "remotion";

import { Lead, Stage } from "../components";
import { run } from "../data";
import { enter, progress } from "../motion";
import { color, size } from "../theme";

/** The triage tag: a strip, a punched hole, and the promise. */
export const Opening = () => {
  const frame = useCurrentFrame();
  const strip = progress(frame, 6, 30);
  return (
    <Stage>
      <div
        style={{ marginTop: "auto", marginBottom: "auto", display: "flex", ...enter(frame, 0, 40) }}
      >
        <div
          style={{
            width: 132,
            backgroundColor: color.raised,
            borderRadius: "6px 0 0 6px",
            border: `2px solid ${color.rule}`,
            borderRight: `4px dashed ${color.background}`,
            position: "relative",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              position: "absolute",
              inset: 0,
              backgroundColor: color.manila,
              scale: `1 ${strip}`,
              transformOrigin: "top",
            }}
          />
          <div
            style={{
              position: "absolute",
              top: 48,
              left: 40,
              width: 48,
              height: 48,
              borderRadius: 24,
              backgroundColor: color.background,
            }}
          />
        </div>
        <div
          style={{
            flex: 1,
            backgroundColor: color.raised,
            border: `2px solid ${color.rule}`,
            borderLeft: "none",
            borderRadius: "0 6px 6px 0",
            padding: "72px 80px",
            display: "flex",
            flexDirection: "column",
            gap: 36,
          }}
        >
          <div style={{ fontSize: 40, fontWeight: 800, color: color.manila, ...enter(frame, 12) }}>
            ARIA
          </div>
          <div
            style={{
              fontSize: size.display,
              fontWeight: 800,
              letterSpacing: "-0.03em",
              lineHeight: 1,
              ...enter(frame, 18),
            }}
          >
            Incident triage that shows its work.
          </div>
          <Lead style={{ maxWidth: 1300, ...enter(frame, 30) }}>
            It reads the logs, scores severity, finds similar incidents and drafts a report in which
            every claim cites evidence. A person approves it.
          </Lead>
        </div>
      </div>
      <p style={{ margin: 0, fontSize: 30, color: color.faint, ...enter(frame, 44) }}>
        A recorded ARIA run.{" "}
        {run.synthetic
          ? "The incident is semi-synthetic: real Loghub lines, composed by ARIA's scenario builder."
          : ""}
      </p>
    </Stage>
  );
};
