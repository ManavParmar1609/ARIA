"use client";

import { useState, type ReactNode } from "react";

import { cx } from "@/lib/cx";

export interface GraphStep {
  title: string;
  body: ReactNode;
  fact: string;
  nodes: string[];
}

type NodeSpec = { id: string; label: string; x: number; y: number; w?: number; kind?: "person" };

// Labels use the console's own words for each step (Read the logs, Rate severity, ...).
const NODES: NodeSpec[] = [
  { id: "plan", label: "plan", x: 180, y: 36 },
  { id: "parse1", label: "read", x: 66, y: 116, w: 64 },
  { id: "parse2", label: "read", x: 142, y: 116, w: 64 },
  { id: "parse3", label: "read", x: 218, y: 116, w: 64 },
  { id: "parse4", label: "read", x: 294, y: 116, w: 64 },
  { id: "merge", label: "combine", x: 180, y: 196 },
  { id: "severity", label: "rate", x: 104, y: 276, w: 112 },
  { id: "recall", label: "find similar", x: 256, y: 276, w: 112 },
  { id: "investigate", label: "investigate", x: 180, y: 356, w: 132 },
  { id: "assess", label: "decide", x: 180, y: 436 },
  { id: "report", label: "write", x: 180, y: 516 },
  { id: "comms", label: "messages", x: 180, y: 596 },
  { id: "review", label: "review", x: 180, y: 676, w: 128, kind: "person" },
  { id: "publish", label: "publish", x: 180, y: 756 },
];
const BY_ID = Object.fromEntries(NODES.map((n) => [n.id, n]));
const H = 34;

// Edges in the order a run takes them; each belongs to the step that first lights its target.
const EDGES: [string, string][] = [
  ["plan", "parse1"],
  ["plan", "parse2"],
  ["plan", "parse3"],
  ["plan", "parse4"],
  ["parse1", "merge"],
  ["parse2", "merge"],
  ["parse3", "merge"],
  ["parse4", "merge"],
  ["merge", "severity"],
  ["merge", "recall"],
  ["severity", "investigate"],
  ["recall", "investigate"],
  ["investigate", "assess"],
  ["assess", "report"],
  ["report", "comms"],
  ["comms", "review"],
  ["review", "publish"],
];

function edgePath(from: NodeSpec, to: NodeSpec): string {
  const y1 = from.y + H / 2;
  const y2 = to.y - H / 2;
  const mid = (y1 + y2) / 2;
  return `M${from.x},${y1} C${from.x},${mid} ${to.x},${mid} ${to.x},${y2}`;
}

const WIDEN = "M246,436 C318,436 318,356 250,356";

/**
 * How a run moves through the graph: four step cards beside the diagram. Pointing at a step, or
 * moving focus into it, lights the part of the diagram it covers; otherwise the whole run is lit.
 */
export function RunGraph({ steps }: { steps: GraphStep[] }) {
  const [picked, setPicked] = useState(-1);
  const lit = new Set((picked >= 0 ? steps.slice(0, picked + 1) : steps).flatMap((s) => s.nodes));
  const current = new Set(picked >= 0 ? (steps[picked]?.nodes ?? []) : []);

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,20rem)] lg:gap-8">
      <ol className="grid content-start gap-4">
        {steps.map((step, i) => (
          <li
            key={step.title}
            id={`how-${i + 1}`}
            onMouseEnter={() => setPicked(i)}
            onMouseLeave={() => setPicked(-1)}
            onFocus={() => setPicked(i)}
            onBlur={() => setPicked(-1)}
            className={cx(
              "grid scroll-mt-24 grid-cols-[2.75rem_minmax(0,1fr)] gap-x-4 rounded-card border bg-raised p-5 transition-colors duration-(--duration-quick) sm:p-6 lg:scroll-mt-8",
              picked === i ? "border-control" : "border-rule",
            )}
          >
            <span
              aria-hidden
              className="tabular grid size-11 place-items-center rounded-full bg-panel-keylime text-lg font-semibold text-heading"
            >
              {i + 1}
            </span>
            <div className="grid content-start gap-3">
              <h3 className="text-xl leading-snug">{step.title}</h3>
              <p className="max-w-prose text-base leading-relaxed text-foreground">{step.body}</p>
              <p className="rounded-md bg-panel-keylime px-4 py-3 text-sm leading-relaxed text-foreground">
                <span className="font-semibold text-heading">In the example: </span>
                {step.fact}
              </p>
            </div>
          </li>
        ))}
      </ol>
      <div className="order-first lg:order-none">
        <div className="rounded-card bg-panel-slate/60 px-4 py-6 sm:px-6 lg:sticky lg:top-6">
          <svg
            viewBox="0 0 360 790"
            className="mx-auto h-auto w-full max-w-xs lg:max-h-[calc(100dvh-6rem)]"
            role="img"
            aria-labelledby="graph-title"
          >
            <title id="graph-title">
              ARIA&apos;s steps: plan, four readers in parallel, combine, then rate the severity and
              find similar incidents at the same time, investigate, decide whether to look further
              (which can widen the search and investigate again), write the report and the messages,
              a person&apos;s review, publish.
            </title>
            <g fill="none" strokeWidth="1.5" strokeLinecap="round">
              {EDGES.map(([a, b]) => {
                const from = BY_ID[a];
                const to = BY_ID[b];
                if (!from || !to) return null;
                return (
                  <path
                    key={`${a}-${b}`}
                    d={edgePath(from, to)}
                    className={cx(
                      "transition-[stroke] duration-(--duration-moderate)",
                      lit.has(b) ? "stroke-foreground/70" : "stroke-control/40",
                    )}
                  />
                );
              })}
              <path
                d={WIDEN}
                strokeDasharray="4 4"
                className={cx(lit.has("assess") ? "stroke-primary" : "stroke-control/60")}
              />
            </g>
            <text
              x="324"
              y="400"
              className="fill-muted-foreground text-[14px] sm:text-[11px]"
              textAnchor="middle"
            >
              widen
            </text>
            {NODES.map((node) => {
              const w = node.w ?? 104;
              const isCurrent = current.has(node.id);
              const isLit = lit.has(node.id);
              return (
                <g key={node.id} transform={`translate(${node.x - w / 2},${node.y - H / 2})`}>
                  <rect
                    width={w}
                    height={H}
                    rx={node.kind === "person" ? H / 2 : 6}
                    className={cx(
                      "transition-[fill,stroke] duration-(--duration-moderate)",
                      isCurrent
                        ? "fill-highlight stroke-primary"
                        : isLit
                          ? "fill-raised stroke-foreground/40"
                          : "fill-background stroke-control/60",
                    )}
                    strokeWidth={isCurrent ? 2 : 1}
                  />
                  {/* The drawing shrinks on a phone, so its labels start larger there. */}
                  <text
                    x={w / 2}
                    y={H / 2}
                    textAnchor="middle"
                    dominantBaseline="central"
                    className={cx(
                      "font-mono text-[14px] sm:text-[12px]",
                      isLit ? "fill-foreground" : "fill-muted-foreground",
                    )}
                  >
                    {node.kind === "person" ? "review (you)" : node.label}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
      </div>
    </div>
  );
}
