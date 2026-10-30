import { useCurrentFrame } from "remotion";

import { Heading, Lead, Rail, Stage } from "../components";
import { run } from "../data";
import { enter, progress } from "../motion";
import { mono, color, radius, size } from "../theme";

/** Drain folds the lines into templates; the bars grow with each template's line count. */
export const Parse = () => {
  const frame = useCurrentFrame();
  const most = Math.max(...run.templates.map((t) => t.count));
  return (
    <Stage>
      <Heading>
        {run.events} lines become {run.nTemplates} templates.
      </Heading>
      <div style={{ display: "flex", flexDirection: "column", gap: 26 }}>
        {run.templates.map((t, i) => {
          const grown = progress(frame, 24 + i * 14, 30);
          return (
            <div
              key={t.text}
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 10,
                ...enter(frame, 20 + i * 14),
              }}
            >
              <div style={{ display: "flex", gap: 20, alignItems: "baseline" }}>
                <span style={{ ...mono, fontSize: size.detail, color: color.foreground }}>
                  {t.text}
                </span>
                {t.novel ? (
                  <span
                    style={{
                      fontSize: 26,
                      color: color.heading,
                      backgroundColor: color.keylime,
                      padding: "4px 12px",
                      borderRadius: radius.small,
                      fontWeight: 500,
                    }}
                  >
                    New: not in routine traffic
                  </span>
                ) : null}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
                <div
                  style={{
                    height: 18,
                    width: `${(t.count / most) * 70 * grown}%`,
                    backgroundColor: t.novel ? color.heading : color.sage,
                    borderRadius: radius.small,
                  }}
                />
                <span
                  style={{ fontSize: 34, fontVariantNumeric: "tabular-nums", color: color.muted }}
                >
                  {Math.round(t.count * grown)} lines
                </span>
              </div>
            </div>
          );
        })}
      </div>
      <Lead style={{ ...enter(frame, 110) }}>
        Before anything else reads them, {run.ips} IP addresses become {run.pseudonyms} pseudonyms,
        and {run.quarantined} line stays in quarantine.
      </Lead>
      <Rail active="Parse" />
    </Stage>
  );
};
