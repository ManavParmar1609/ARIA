import { useCurrentFrame } from "remotion";

import { Heading, Lead, Panel, Rail, SevBadge, Stage } from "../components";
import { cited, review } from "../data";
import { enter, progress } from "../motion";
import { color, size } from "../theme";

const KIND: Record<string, string> = {
  slack: "Slack message to responders",
  webhook: "Update for stakeholders",
  status_page: "Status page draft",
};

/** The run waits at its checkpoint; a person approves; the report joins memory. */
export const Review = () => {
  const frame = useCurrentFrame();
  const approved = progress(frame, 140, 18);
  return (
    <Stage>
      <Heading>Then it waits for a person.</Heading>
      <Panel style={{ display: "flex", flexDirection: "column", gap: 26 }}>
        <div style={{ display: "flex", gap: 22, alignItems: "center" }}>
          <SevBadge severity={cited.severity} />
          <span style={{ fontSize: size.body, fontWeight: 800 }}>{cited.title}</span>
          <span
            style={{
              marginLeft: "auto",
              fontSize: 34,
              fontWeight: 800,
              color: approved > 0.5 ? color.ok : color.manila,
            }}
          >
            {approved > 0.5 ? "Published" : "Waiting for a person to approve"}
          </span>
        </div>
        {review.actions.map((action, i) => (
          <div
            key={action.kind}
            style={{
              display: "flex",
              gap: 22,
              fontSize: 32,
              color: color.muted,
              ...enter(frame, 30 + i * 16),
            }}
          >
            <span style={{ width: 520, color: color.foreground }}>
              {KIND[action.kind] ?? action.kind}
            </span>
            <span>{action.title}</span>
            <span style={{ marginLeft: "auto", color: color.faint }}>draft, not sent</span>
          </div>
        ))}
      </Panel>
      <div style={{ display: "flex", gap: 32, alignItems: "center" }}>
        <div
          style={{
            fontSize: size.body,
            fontWeight: 800,
            padding: "16px 40px",
            borderRadius: 6,
            backgroundColor: approved > 0.5 ? color.ok : color.manila,
            color: color.ink,
            scale: `${1 - 0.06 * Math.sin(Math.PI * approved)}`,
            ...enter(frame, 90),
          }}
        >
          {approved > 0.5 ? "Approved" : "Approve"}
        </div>
        <Lead style={{ opacity: approved }}>
          Published and added to incident memory. Each message goes out only once a person approves
          it too.
        </Lead>
      </div>
      <Lead style={{ fontSize: 34, ...enter(frame, 60) }}>
        From the first line to this pause: {review.timeToReview}, offline.
      </Lead>
      <Rail active="Review" />
    </Stage>
  );
};
