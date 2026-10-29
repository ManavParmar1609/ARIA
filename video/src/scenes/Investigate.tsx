import { useCurrentFrame } from "remotion";

import { Heading, Panel, Rail, SevBadge, Stage } from "../components";
import { investigate } from "../data";
import { enter, progress } from "../motion";
import { mono, color, size } from "../theme";

/** Read-only tool calls test the hypotheses; then memory brings back the closest past incidents. */
export const Investigate = () => {
  const frame = useCurrentFrame();
  const recall = progress(frame, 170, 24);
  return (
    <Stage>
      <Heading>Hypotheses, tested with read-only tools.</Heading>
      <div style={{ display: "flex", gap: 56 }}>
        <Panel style={{ width: 640, display: "flex", flexDirection: "column", gap: 18 }}>
          {investigate.tools.map((tool, i) => (
            <div
              key={tool}
              style={{
                display: "flex",
                gap: 18,
                alignItems: "center",
                ...mono,
                fontSize: size.detail,
                ...enter(frame, 16 + i * 16),
              }}
            >
              <span style={{ color: color.ok, fontFamily: "inherit" }}>ok</span>
              <span>{tool}</span>
            </div>
          ))}
        </Panel>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 24 }}>
          {investigate.hypotheses.map((h, i) => {
            const lead = i === 0;
            return (
              <Panel
                key={h.name}
                style={{
                  padding: 32,
                  outline: lead ? `4px solid ${color.ink}` : "none",
                  outlineOffset: -3,
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "baseline",
                  ...enter(frame, 100 + i * 20),
                }}
              >
                <span
                  style={{
                    fontSize: size.body,
                    fontWeight: lead ? 500 : 400,
                    color: lead ? color.heading : color.foreground,
                  }}
                >
                  {h.name.charAt(0).toUpperCase() + h.name.slice(1)}
                </span>
                <span
                  style={{ fontSize: 34, color: color.muted, fontVariantNumeric: "tabular-nums" }}
                >
                  {h.status}, {Math.round(100 * h.confidence)}%
                </span>
              </Panel>
            );
          })}
        </div>
      </div>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 16,
          opacity: recall,
          translate: `0px ${(1 - recall) * 20}px`,
        }}
      >
        <div style={{ fontSize: size.body, fontWeight: 500, color: color.heading }}>
          The closest past incidents, and the runbook they used
        </div>
        <div style={{ display: "flex", gap: 24 }}>
          {investigate.incidents.map((incident) => (
            <Panel
              key={incident.title}
              style={{ flex: 1, padding: 28, display: "flex", flexDirection: "column", gap: 14 }}
            >
              <SevBadge severity={incident.severity} scale={0.75} />
              <span style={{ fontSize: 32, lineHeight: 1.2 }}>{incident.title}</span>
              <span style={{ fontSize: 28, color: color.faint }}>seen {incident.seen} times</span>
            </Panel>
          ))}
        </div>
        <span style={{ ...mono, fontSize: size.detail, color: color.ink }}>
          runbook: {investigate.runbook}
        </span>
      </div>
      <Rail active="Investigate" />
    </Stage>
  );
};
