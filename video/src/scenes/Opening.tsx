import type { ReactNode } from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";

import { assessment, cited, run } from "../data";
import { enter, progress } from "../motion";
import { SANS, color, mono, radius, serif, sevColor } from "../theme";

/** A cream card on the slate panel, its name in a small pill beneath, rising into place. */
const Card = ({ name, at, children }: { name: string; at: number; children: ReactNode }) => {
  const frame = useCurrentFrame();
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18, ...enter(frame, at, 48) }}>
      <div
        style={{
          backgroundColor: color.raised,
          borderRadius: 16,
          padding: 28,
          minHeight: 470,
          display: "flex",
          flexDirection: "column",
          gap: 18,
        }}
      >
        {children}
      </div>
      <span
        style={{
          alignSelf: "center",
          backgroundColor: color.raised,
          color: color.heading,
          borderRadius: 999,
          padding: "4px 18px",
          fontSize: 24,
          fontWeight: 500,
        }}
      >
        {name}
      </span>
    </div>
  );
};

/** The landing page's hero: the promise on sage, the recorded run in three cards on slate. */
export const Opening = () => {
  const frame = useCurrentFrame();
  const thread = progress(frame, 30, 40);
  const claim = cited.claims[0];
  const p = Math.round(
    100 * (assessment.probabilities.find((s) => s.severity === assessment.severity)?.p ?? 0),
  );
  return (
    <AbsoluteFill
      style={{
        backgroundColor: color.background,
        fontFamily: SANS,
        padding: 48,
        display: "grid",
        gridTemplateColumns: "11fr 13fr",
        gap: 24,
      }}
    >
      <div
        style={{
          backgroundColor: color.sage,
          borderRadius: radius.panel,
          padding: "76px 64px 64px",
          display: "flex",
          flexDirection: "column",
          color: color.heading,
        }}
      >
        <h1
          style={{
            margin: 0,
            ...serif,
            fontSize: 112,
            lineHeight: 1.02,
            letterSpacing: "-0.03em",
            maxWidth: "13ch",
            ...enter(frame, 4, 36),
          }}
        >
          Turn a wall of logs into a report you can check.
        </h1>
        <p
          style={{
            margin: "auto 0 0",
            fontSize: 34,
            lineHeight: 1.35,
            maxWidth: 700,
            ...enter(frame, 18),
          }}
        >
          ARIA reads an alert&apos;s logs, rates how serious it is, finds what happened before and
          drafts the report, with every claim citing its log line. Nothing is sent without your
          approval.
        </p>
        <p style={{ margin: "24px 0 0", fontSize: 24, maxWidth: 700, ...enter(frame, 30) }}>
          A recorded ARIA run.
          {run.synthetic
            ? " The incident is semi-synthetic: real Loghub lines, composed by ARIA's scenario builder."
            : ""}
        </p>
      </div>
      <div
        style={{
          backgroundColor: color.slate,
          borderRadius: radius.panel,
          padding: 44,
          display: "grid",
          alignContent: "center",
          position: "relative",
        }}
      >
        {/* A thin thread through the cards, drawn once they have risen. */}
        <div
          style={{
            position: "absolute",
            left: "8%",
            right: "8%",
            top: "46%",
            height: 3,
            backgroundColor: "rgb(15 62 23 / 0.25)",
            transformOrigin: "left center",
            scale: `${thread} 1`,
          }}
        />
        <div
          style={{
            position: "relative",
            display: "grid",
            gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
            gap: 20,
          }}
        >
          <Card name="Alert" at={8}>
            <span
              style={{
                width: 60,
                height: 60,
                borderRadius: 30,
                backgroundColor: color.keylime,
                display: "grid",
                placeItems: "center",
              }}
            >
              <svg width={30} height={30} viewBox="0 0 24 24" fill="none">
                <path
                  d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0"
                  stroke={color.heading}
                  strokeWidth={1.6}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </span>
            <span
              style={{
                ...serif,
                fontSize: 40,
                lineHeight: 1.1,
                letterSpacing: "-0.01em",
                color: color.heading,
              }}
            >
              {run.title}
            </span>
            <span style={{ fontSize: 22, color: color.muted, lineHeight: 1.35 }}>
              {run.system}, {run.lines} lines over {run.span}
            </span>
            <span
              style={{
                marginTop: "auto",
                alignSelf: "flex-start",
                backgroundColor: color.keylime,
                color: color.heading,
                borderRadius: 999,
                padding: "4px 14px",
                fontSize: 22,
                fontWeight: 500,
              }}
            >
              Triaged
            </span>
          </Card>
          <Card name="Severity" at={20}>
            <span style={{ ...serif, fontSize: 44, color: color.heading, lineHeight: 1 }}>
              {assessment.severity}
              <span style={{ fontFamily: SANS, fontSize: 22, color: color.muted, marginLeft: 12 }}>
                {p}% likely
              </span>
            </span>
            <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 8 }}>
              {assessment.probabilities.map((item) => {
                const inSet = assessment.set.includes(item.severity);
                return (
                  <div
                    key={item.severity}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "70px 1fr",
                      alignItems: "center",
                      gap: 12,
                      fontSize: 22,
                    }}
                  >
                    <span
                      style={{
                        fontWeight: inSet ? 600 : 400,
                        color: inSet ? color.heading : color.muted,
                      }}
                    >
                      {item.severity}
                    </span>
                    <span style={{ height: 12, borderRadius: 6, backgroundColor: color.sunken }}>
                      <span
                        style={{
                          display: "block",
                          height: "100%",
                          borderRadius: 6,
                          width: `${Math.max(4, Math.round(item.p * 100 * progress(frame, 34, 30)))}%`,
                          backgroundColor: inSet ? color.heading : sevColor[item.severity],
                        }}
                      />
                    </span>
                  </div>
                );
              })}
            </div>
            <span style={{ marginTop: "auto", fontSize: 22, color: color.muted }}>
              Short list: {assessment.set.join(" or ")}
            </span>
          </Card>
          <Card name="Report" at={32}>
            <span style={{ fontSize: 22, fontWeight: 500, color: color.muted }}>
              Claim 1 of {cited.claims.length}
            </span>
            <span
              style={{
                fontSize: 26,
                lineHeight: 1.35,
                color: color.foreground,
                display: "-webkit-box",
                WebkitLineClamp: 5,
                WebkitBoxOrient: "vertical",
                overflow: "hidden",
              }}
            >
              {claim?.text}
            </span>
            <span style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {(claim?.ids ?? []).slice(0, 3).map((id) => (
                <span
                  key={id}
                  style={{
                    ...mono,
                    fontSize: 20,
                    color: color.heading,
                    backgroundColor: color.mint,
                    borderRadius: 999,
                    padding: "2px 12px",
                  }}
                >
                  {id}
                </span>
              ))}
            </span>
            {/* A status, not a button: nobody approves anything in a video. */}
            <span style={{ marginTop: "auto", fontSize: 22, color: color.muted }}>
              Waiting for a person to approve
            </span>
          </Card>
        </div>
      </div>
    </AbsoluteFill>
  );
};
