import { type CSSProperties } from "react";

import { SEVERITIES, SEVERITY_MEANING, type Severity } from "@/lib/api/types";
import { cx } from "@/lib/cx";

export const SEVERITY_BG: Record<Severity, string> = {
  SEV1: "bg-sev1",
  SEV2: "bg-sev2",
  SEV3: "bg-sev3",
  SEV4: "bg-sev4",
};

export const SEVERITY_FG: Record<Severity, string> = {
  SEV1: "text-sev1-fg",
  SEV2: "text-sev2-fg",
  SEV3: "text-sev3-fg",
  SEV4: "text-sev4-fg",
};

const SHORT: Record<Severity, string> = {
  SEV1: "Critical",
  SEV2: "High",
  SEV3: "Moderate",
  SEV4: "Low",
};

/**
 * Severity as a small tag: the colour strip carries the level and the text says it, so the
 * meaning never depends on colour alone.
 */
export function SeverityBadge({
  severity,
  className,
  size = "md",
  withMeaning = false,
}: {
  severity: Severity | null | undefined;
  className?: string;
  size?: "sm" | "md";
  withMeaning?: boolean;
}) {
  if (!severity) {
    return (
      <span
        className={cx(
          "tabular inline-flex items-center rounded-xs border border-dashed border-control px-1.5 font-medium text-faint",
          size === "sm" ? "h-5 text-xs" : "h-6 text-xs",
          className,
        )}
      >
        Not rated
      </span>
    );
  }
  return (
    <span
      className={cx("inline-flex items-center gap-2", className)}
      title={SEVERITY_MEANING[severity]}
    >
      <span
        className={cx(
          "tabular inline-flex items-center rounded-xs border border-sev-edge px-1.5 font-medium text-sev-ink",
          SEVERITY_BG[severity],
          size === "sm" ? "h-5 text-[0.6875rem]" : "h-6 text-xs",
        )}
      >
        {severity}
      </span>
      {withMeaning ? (
        <span className="text-sm text-muted-foreground">{SHORT[severity]}</span>
      ) : null}
    </span>
  );
}

/** The severity strip down a card's edge: its colour and its label, in dark ink. */
export function TagStrip({
  severity,
  className,
  style,
}: {
  severity: Severity | null | undefined;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <div
      className={cx(
        "relative flex shrink-0 flex-col items-center pt-5",
        severity ? SEVERITY_BG[severity] : "bg-sunken",
        className,
      )}
      style={style}
    >
      <span
        className={cx(
          "tabular text-sm font-medium tracking-[0.04em]",
          severity ? "text-sev-ink" : "text-faint",
        )}
      >
        {severity ?? "—"}
      </span>
    </div>
  );
}

/**
 * The severity instrument: model probability per level, the conformal prediction set as a
 * bracket, the safety floor if one applied, and the decision filled in its colour.
 */
export function SeverityScale({
  probabilities,
  predictionSet,
  decided,
  floor,
  alpha = 0.1,
  setEmpty = false,
  compact = false,
  className,
}: {
  probabilities: Partial<Record<Severity, number>>;
  predictionSet: Severity[];
  decided: Severity;
  floor?: Severity | null;
  alpha?: number;
  /** No class reached the conformal threshold: the bracket is drawn dashed, as a stand-in. */
  setEmpty?: boolean;
  compact?: boolean;
  className?: string;
}) {
  const inSet = new Set(predictionSet);
  const setIdx = SEVERITIES.map((s, i) => (inSet.has(s) ? i : -1)).filter((i) => i >= 0);
  const first = Math.min(...setIdx);
  const last = Math.max(...setIdx);
  const barMax = compact ? 44 : 72;
  const coverage = Math.round((1 - alpha) * 100);
  const described = SEVERITIES.map(
    (s) => `${s} ${Math.round((probabilities[s] ?? 0) * 100)}%`,
  ).join(", ");
  return (
    <figure
      className={cx("grid gap-1", className)}
      aria-label={`Model probabilities: ${described}. ${setEmpty ? `No class is likely enough for the ${coverage}% prediction set.` : `${coverage}% prediction set: ${predictionSet.join(", ")}.`} Decided: ${decided}.${floor ? ` Safety floor: ${floor}.` : ""}`}
    >
      <div className="relative grid grid-cols-4 gap-1.5" aria-hidden>
        {setIdx.length > 0 ? (
          <div
            className={cx(
              "pointer-events-none absolute -top-0.5 h-2 rounded-t-xs border-x border-t",
              setEmpty ? "border-dashed border-faint" : "border-foreground/60",
            )}
            style={{
              left: `calc(${(first / 4) * 100}% + 2px)`,
              width: `calc(${((last - first + 1) / 4) * 100}% - 6px)`,
            }}
          />
        ) : null}
        {SEVERITIES.map((s) => {
          const p = probabilities[s] ?? 0;
          const isDecided = s === decided;
          return (
            <div key={s} className="flex flex-col items-center justify-end gap-1 pt-3">
              <span
                className={cx(
                  "tabular text-xs",
                  isDecided ? "font-medium text-foreground" : "text-muted-foreground",
                )}
              >
                {Math.round(p * 100)}%
              </span>
              <div className="flex w-full items-end justify-center" style={{ height: barMax }}>
                <div
                  data-bar
                  className={cx(
                    "w-full max-w-10 rounded-t-xs",
                    isDecided ? SEVERITY_BG[s] : inSet.has(s) ? "bg-control" : "bg-rule",
                  )}
                  style={{ height: Math.max(2, Math.round(p * barMax)) }}
                />
              </div>
            </div>
          );
        })}
      </div>
      <div className="grid grid-cols-4 gap-1.5 border-t border-rule pt-1" aria-hidden>
        {SEVERITIES.map((s) => (
          <span
            key={s}
            className={cx(
              "tabular text-center text-xs font-medium",
              s === decided ? "text-foreground" : "text-faint",
            )}
          >
            {s}
            {floor === s ? (
              <span className="block text-[0.6875rem] text-muted-foreground">floor</span>
            ) : null}
          </span>
        ))}
      </div>
      {!compact ? (
        <figcaption className="text-xs text-muted-foreground">
          Bars: calibrated model probability.{" "}
          {setEmpty
            ? `Dashed bracket: no class is likely enough for the ${coverage}% prediction set, so it stands in with the most likely.`
            : `Bracket: the ${coverage}% prediction set.`}
        </figcaption>
      ) : null}
    </figure>
  );
}
