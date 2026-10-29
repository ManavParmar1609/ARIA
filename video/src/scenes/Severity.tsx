import { useCurrentFrame } from "remotion";

import { Heading, Lead, Panel, Rail, SevBadge, Stage } from "../components";
import { assessment } from "../data";
import { enter, progress } from "../motion";
import { color, radius, sevColor, size } from "../theme";

const BAR_HEIGHT = 230;

/** Rules, then calibrated probabilities, then the conformal set, then the decision. */
export const Severity = () => {
  const frame = useCurrentFrame();
  const bracket = progress(frame, 190, 30);
  const decided = progress(frame, 260, 24);
  const inSet = new Set(assessment.set);
  return (
    <Stage>
      <Heading>Severity: rules, a model, then a prediction set.</Heading>
      <div style={{ display: "flex", gap: 56, alignItems: "stretch" }}>
        <Panel style={{ width: 640, display: "flex", flexDirection: "column", gap: 22 }}>
          <div
            style={{
              fontSize: size.body,
              fontWeight: 500,
              color: color.heading,
              ...enter(frame, 14),
            }}
          >
            Rules point to <SevBadge severity={assessment.rule} scale={0.9} />
          </div>
          {assessment.hits.map((hit, i) => (
            <div
              key={hit.title}
              style={{
                display: "flex",
                gap: 16,
                alignItems: "center",
                fontSize: 32,
                color: color.muted,
                ...enter(frame, 34 + i * 16),
              }}
            >
              <SevBadge severity={hit.severity} scale={0.7} />
              <span>{hit.title}</span>
            </div>
          ))}
        </Panel>
        <Panel style={{ flex: 1, display: "flex", flexDirection: "column", gap: 20 }}>
          <div
            style={{
              fontSize: size.body,
              fontWeight: 500,
              color: color.heading,
              ...enter(frame, 90),
            }}
          >
            Calibrated model
          </div>
          <div
            style={{
              display: "flex",
              gap: 40,
              alignItems: "flex-end",
              height: BAR_HEIGHT + 120,
              position: "relative",
            }}
          >
            {assessment.probabilities.map((item, i) => {
              const grown = progress(frame, 100 + i * 10, 40);
              const set = inSet.has(item.severity);
              return (
                <div
                  key={item.severity}
                  style={{
                    flex: 1,
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    gap: 12,
                    position: "relative",
                  }}
                >
                  {set ? (
                    <div
                      style={{
                        position: "absolute",
                        top: -20,
                        left: -14,
                        right: -14,
                        bottom: 54,
                        border: `4px solid ${color.ink}`,
                        borderBottom: "none",
                        borderRadius: `${radius.small}px ${radius.small}px 0 0`,
                        opacity: bracket,
                      }}
                    />
                  ) : null}
                  <span
                    style={{
                      fontSize: 34,
                      fontVariantNumeric: "tabular-nums",
                      fontWeight: set ? 500 : 400,
                      color: set ? color.heading : color.muted,
                    }}
                  >
                    {(100 * item.p * grown).toFixed(1)}%
                  </span>
                  <div
                    style={{
                      width: "70%",
                      height: Math.max(4, BAR_HEIGHT * item.p * grown),
                      backgroundColor: sevColor[item.severity],
                      borderRadius: radius.small,
                    }}
                  />
                  <SevBadge severity={item.severity} scale={0.8} />
                </div>
              );
            })}
          </div>
          <div style={{ fontSize: 32, color: color.ink, opacity: bracket }}>
            The {assessment.coverage} prediction set: {"{"}
            {assessment.set.join(", ")}
            {"}"}
          </div>
        </Panel>
      </div>
      <div
        style={{
          display: "flex",
          gap: 28,
          alignItems: "center",
          opacity: decided,
          translate: `0px ${(1 - decided) * 20}px`,
        }}
      >
        <SevBadge severity={assessment.severity} scale={1.3} />
        <Lead style={{ color: color.foreground }}>
          The model is {Math.round(100 * assessment.confidence)}% sure: not enough to decide alone,
          so a person confirms it.
        </Lead>
      </div>
      <Rail active="Severity" />
    </Stage>
  );
};
