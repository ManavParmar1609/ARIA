import { useCurrentFrame } from "remotion";

import { Chip, Heading, Panel, Rail, SevBadge, Stage } from "../components";
import { cited } from "../data";
import { enter, progress } from "../motion";
import { mono, color, radius, size } from "../theme";

const FOCUS_CLAIM = 1; // the claim about the new warning template, which cites E2

/** Claims arrive with their citations; one citation opens its evidence. */
export const Report = () => {
  const frame = useCurrentFrame();
  const focus = progress(frame, 230, 24);
  const validated = progress(frame, 300, 20);
  return (
    <Stage>
      <Heading>Every claim cites its evidence.</Heading>
      <div style={{ display: "flex", gap: 40, alignItems: "flex-start" }}>
        <Panel style={{ flex: 1.45, display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ display: "flex", gap: 20, alignItems: "center", ...enter(frame, 10) }}>
            <SevBadge severity={cited.severity} />
            <span style={{ fontSize: size.body, fontWeight: 500, color: color.heading }}>
              {cited.title}
            </span>
          </div>
          {cited.claims.slice(1).map((claim, i) => (
            <div
              key={claim.text}
              style={{
                fontSize: 30,
                lineHeight: 1.3,
                padding: "6px 10px",
                borderRadius: radius.small,
                backgroundColor:
                  i === FOCUS_CLAIM ? `rgba(203, 255, 252, ${0.16 * focus})` : "transparent",
                ...enter(frame, 30 + i * 26),
              }}
            >
              {claim.text}
              {claim.ids.slice(0, 3).map((id) => (
                <Chip
                  key={id}
                  id={id}
                  lit={i === FOCUS_CLAIM && focus > 0.5 && id === cited.focus?.id}
                />
              ))}
              {claim.ids.length > 3 ? <Chip id={`+${claim.ids.length - 3}`} /> : null}
            </div>
          ))}
        </Panel>
        {cited.focus ? (
          <Panel
            style={{
              flex: 1,
              backgroundColor: color.sunken,
              outline: `4px solid ${color.ink}`,
              outlineOffset: -3,
              display: "flex",
              flexDirection: "column",
              gap: 18,
              opacity: focus,
              translate: `${(1 - focus) * 40}px 0px`,
            }}
          >
            <span
              style={{
                fontSize: 26,
                color: color.ink,
                backgroundColor: color.grass,
                alignSelf: "flex-start",
                padding: "4px 12px",
                borderRadius: radius.small,
                fontWeight: 500,
              }}
            >
              {cited.focus.id}: {cited.focus.kind}
            </span>
            <span style={{ ...mono, fontSize: 28, lineHeight: 1.35, overflowWrap: "anywhere" }}>
              {cited.focus.title}
            </span>
            <span
              style={{
                ...mono,
                fontSize: 26,
                color: color.muted,
                lineHeight: 1.35,
                overflowWrap: "anywhere",
              }}
            >
              {cited.focus.detail}
            </span>
          </Panel>
        ) : null}
      </div>
      <div style={{ fontSize: size.lead, color: color.ok, opacity: validated }}>
        Validated: {cited.checked} claims checked, {cited.coverage} cited.
      </div>
      <Rail active="Report" />
    </Stage>
  );
};
