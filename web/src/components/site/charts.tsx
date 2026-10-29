import type { MethodScore } from "@/lib/site-data";
import { cn } from "@/lib/utils";

const pct = (x: number, digits = 1) => `${(x * 100).toFixed(digits)}%`;

/**
 * Accuracy with its 95% bootstrap interval for each severity method, best first. Real HTML text
 * on a 0-100% scale, so it reads at any width and needs no script.
 */
export function BaselineChart({
  methods,
  className,
}: {
  methods: MethodScore[];
  className?: string;
}) {
  const row =
    "grid grid-cols-[minmax(0,1fr)_3.5rem] items-center gap-x-3 gap-y-1 sm:grid-cols-[minmax(10rem,15rem)_minmax(0,1fr)_3.5rem]";
  return (
    <figure className={cn("grid gap-3", className)}>
      <div
        role="table"
        aria-label="Severity accuracy by method, with 95% confidence intervals"
        className="grid gap-2.5"
      >
        <div role="row" className={row}>
          <span role="columnheader">
            <span className="sr-only">Method</span>
          </span>
          <span
            role="columnheader"
            aria-hidden
            className="relative hidden h-4 text-xs text-faint sm:block"
          >
            {[0, 25, 50, 75, 100].map((tick) => (
              <span
                key={tick}
                // the end ticks sit inside the track, so "100%" never runs into "Accuracy"
                className={cn(
                  "tabular absolute",
                  tick === 0 ? "" : tick === 100 ? "-translate-x-full" : "-translate-x-1/2",
                )}
                style={{ left: `${tick}%` }}
              >
                {tick}%
              </span>
            ))}
          </span>
          <span
            role="columnheader"
            className="col-start-2 text-right text-xs text-faint sm:col-start-3"
          >
            Accuracy
          </span>
        </div>
        {methods.map((m) => {
          const isAria = m.key === "aria_policy";
          return (
            <div role="row" key={m.key} className={row}>
              <span
                role="cell"
                className={cn(
                  "text-sm leading-tight",
                  isAria ? "font-medium text-foreground" : "text-muted-foreground",
                )}
              >
                {m.label}
              </span>
              <span
                role="cell"
                aria-label={`95% interval ${pct(m.low)} to ${pct(m.high)}`}
                className="relative col-span-2 row-start-2 h-5 sm:col-span-1 sm:col-start-2 sm:row-start-1"
              >
                {[25, 50, 75].map((tick) => (
                  <span
                    key={tick}
                    aria-hidden
                    className="absolute inset-y-0 w-px bg-rule"
                    style={{ left: `${tick}%` }}
                  />
                ))}
                <span
                  aria-hidden
                  className={cn(
                    "absolute top-1/2 h-0.5 -translate-y-1/2 rounded-full",
                    isAria ? "bg-primary" : "bg-control",
                  )}
                  style={{ left: `${m.low * 100}%`, width: `${(m.high - m.low) * 100}%` }}
                />
                <span
                  aria-hidden
                  className={cn(
                    "absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2",
                    isAria ? "border-pop-ink bg-grass" : "border-foreground/70 bg-background",
                  )}
                  style={{ left: `${m.accuracy * 100}%` }}
                />
              </span>
              <span
                role="cell"
                className={cn(
                  "tabular col-start-2 row-start-1 text-right text-sm sm:col-start-3",
                  isAria ? "font-medium" : "text-muted-foreground",
                )}
              >
                {pct(m.accuracy)}
              </span>
            </div>
          );
        })}
      </div>
      <figcaption className="text-xs text-muted-foreground">
        Dots: accuracy on the same windows. Lines: 95% bootstrap confidence intervals.
      </figcaption>
    </figure>
  );
}

/**
 * Risk-coverage: the error rate among the windows ARIA would decide alone, as it decides more
 * of them. The marked point is the policy ARIA runs.
 */
export function RiskCoverageChart({
  points,
  operating,
  className,
}: {
  points: { coverage: number; risk: number }[];
  operating: { coverage: number; accuracy: number };
  className?: string;
}) {
  const W = 360;
  const Hh = 200;
  const pad = { l: 40, r: 12, t: 12, b: 34 };
  const x = (c: number) => pad.l + ((c - 0.5) / 0.5) * (W - pad.l - pad.r);
  const y = (r: number) => pad.t + (1 - r / 0.1) * (Hh - pad.t - pad.b);
  const path = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(p.coverage).toFixed(1)},${y(p.risk).toFixed(1)}`)
    .join(" ");
  const opRisk = 1 - operating.accuracy;
  return (
    <figure className={cn("grid gap-2", className)}>
      <svg
        viewBox={`0 0 ${W} ${Hh}`}
        className="h-auto w-full max-w-md"
        role="img"
        aria-label={`Risk against coverage. At ${pct(operating.coverage)} coverage, ARIA's policy errs on ${pct(opRisk)} of the windows it decides alone; deciding all of them would raise that to ${pct(points.at(-1)?.risk ?? 0)}.`}
      >
        <g className="text-[10px]">
          {[0, 0.025, 0.05, 0.075, 0.1].map((r) => (
            <g key={r}>
              <line x1={pad.l} x2={W - pad.r} y1={y(r)} y2={y(r)} className="stroke-rule" />
              <text x={pad.l - 6} y={y(r) + 3} textAnchor="end" className="tabular fill-faint">
                {(r * 100).toFixed(r === 0 || r === 0.05 || r === 0.1 ? 0 : 1)}%
              </text>
            </g>
          ))}
          {[0.5, 0.6, 0.7, 0.8, 0.9, 1].map((c) => (
            <text
              key={c}
              x={x(c)}
              y={Hh - pad.b + 14}
              textAnchor="middle"
              className="tabular fill-faint"
            >
              {Math.round(c * 100)}%
            </text>
          ))}
          <text
            x={(pad.l + W - pad.r) / 2}
            y={Hh - 4}
            textAnchor="middle"
            className="fill-muted-foreground"
          >
            share of windows ARIA decides without a person
          </text>
          <text
            transform={`translate(10 ${(pad.t + Hh - pad.b) / 2}) rotate(-90)`}
            textAnchor="middle"
            className="fill-muted-foreground"
          >
            error rate
          </text>
        </g>
        <path d={path} fill="none" strokeWidth="2" className="stroke-foreground/80" />
        {points.map((p) => (
          <circle
            key={p.coverage}
            cx={x(p.coverage)}
            cy={y(p.risk)}
            r="2.5"
            className="fill-foreground/80"
          />
        ))}
        <circle
          cx={x(operating.coverage)}
          cy={y(opRisk)}
          r="5"
          className="fill-primary stroke-background"
          strokeWidth="2"
        />
        <text
          x={x(operating.coverage) - 8}
          y={y(opRisk) - 10}
          textAnchor="end"
          className="fill-foreground text-[11px] font-medium"
        >
          ARIA today
        </text>
      </svg>
      <figcaption className="text-xs text-muted-foreground">
        Lower is better. Each point decides the most confident windows first.
      </figcaption>
    </figure>
  );
}
