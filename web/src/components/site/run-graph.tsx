"use client";

import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useRef, useState } from "react";

import { cn } from "@/lib/utils";

gsap.registerPlugin(useGSAP, ScrollTrigger);

export interface GraphStep {
  title: string;
  body: string;
  fact: string;
  nodes: string[];
}

type NodeSpec = { id: string; label: string; x: number; y: number; w?: number; kind?: "person" };

const NODES: NodeSpec[] = [
  { id: "plan", label: "plan", x: 180, y: 36 },
  { id: "parse1", label: "parse", x: 66, y: 116, w: 64 },
  { id: "parse2", label: "parse", x: 142, y: 116, w: 64 },
  { id: "parse3", label: "parse", x: 218, y: 116, w: 64 },
  { id: "parse4", label: "parse", x: 294, y: 116, w: 64 },
  { id: "merge", label: "merge", x: 180, y: 196 },
  { id: "severity", label: "severity", x: 104, y: 276, w: 112 },
  { id: "recall", label: "recall", x: 256, y: 276, w: 112 },
  { id: "investigate", label: "investigate", x: 180, y: 356, w: 132 },
  { id: "assess", label: "assess", x: 180, y: 436 },
  { id: "report", label: "report", x: 180, y: 516 },
  { id: "comms", label: "comms", x: 180, y: 596 },
  { id: "review", label: "review", x: 180, y: 676, kind: "person" },
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
 * How a run moves through the graph. The diagram stays in view while the steps scroll past;
 * each step lights the nodes it covers. With reduced motion, or on small screens, everything
 * is drawn at once and the steps read as a list.
 */
export function RunGraph({ steps }: { steps: GraphStep[] }) {
  const root = useRef<HTMLDivElement>(null);
  const animated = useRef(false);
  const [active, setActive] = useState(-1);
  const lit = new Set(steps.slice(0, active + 1).flatMap((s) => s.nodes));
  const current = new Set(active >= 0 ? (steps[active]?.nodes ?? []) : []);

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add("(min-width: 1024px) and (prefers-reduced-motion: no-preference)", () => {
        const items = gsap.utils.toArray<HTMLElement>("[data-step]");
        // The active step is the last one whose top has passed 60% of the viewport, so the zones
        // touch and a fast scroll cannot skip a step.
        const pick = () => {
          const line = window.innerHeight * 0.6;
          let index = -1;
          items.forEach((item, i) => {
            if (item.getBoundingClientRect().top <= line) index = i;
          });
          setActive(index);
        };
        ScrollTrigger.create({
          trigger: "[data-steps]",
          start: "top bottom",
          end: "bottom top",
          onUpdate: pick,
          onRefresh: pick,
        });
        void document.fonts?.ready.then(() => ScrollTrigger.refresh());
        // Edges start undrawn; the effect below draws each one when its target node lights up.
        for (const path of gsap.utils.toArray<SVGPathElement>("[data-edge]")) {
          const length = path.getTotalLength();
          gsap.set(path, { strokeDasharray: length, strokeDashoffset: length });
        }
        animated.current = true;
        return () => {
          animated.current = false;
          setActive(-1);
        };
      });
      mm.add("(max-width: 1023px), (prefers-reduced-motion: reduce)", () => {
        setActive(steps.length - 1);
      });
      return () => mm.revert();
    },
    { scope: root },
  );

  useGSAP(
    () => {
      if (!animated.current) return;
      for (const path of gsap.utils.toArray<SVGPathElement>("[data-edge]")) {
        const on = lit.has(path.dataset.target ?? "");
        gsap.to(path, {
          strokeDashoffset: on ? 0 : path.getTotalLength(),
          duration: on ? 0.55 : 0.25,
          ease: on ? "power2.inOut" : "power1.in",
          overwrite: true,
        });
      }
    },
    { scope: root, dependencies: [active] },
  );

  return (
    <div ref={root} className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)] lg:gap-16">
      <ol data-steps className="grid gap-6 lg:gap-[22vh] lg:py-[12vh]">
        {steps.map((step, i) => (
          <li
            key={step.title}
            data-step
            className={cn(
              "grid grid-cols-[2.5rem_1fr] gap-x-4 transition-opacity duration-(--duration-slow) lg:opacity-40",
              (i === active || active === -1) && "lg:opacity-100",
            )}
            aria-current={i === active ? "step" : undefined}
          >
            <span
              className={cn(
                "tabular flex size-10 items-center justify-center rounded-full border text-sm font-bold transition-colors duration-(--duration-moderate)",
                i <= active
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-control text-muted-foreground",
              )}
              aria-hidden
            >
              {i + 1}
            </span>
            <div>
              <h3 className="text-xl leading-tight font-bold">{step.title}</h3>
              <p className="mt-2 max-w-prose text-base text-muted-foreground">{step.body}</p>
              <p className="mt-3 inline-block rounded-xs border-l-2 border-primary bg-sunken px-3 py-1.5 text-sm">
                {step.fact}
              </p>
            </div>
          </li>
        ))}
      </ol>
      <div className="order-first lg:order-none">
        <div className="lg:sticky lg:top-[10vh]">
          <svg
            viewBox="0 0 360 790"
            className="mx-auto h-auto w-full max-w-sm lg:max-h-[80vh]"
            role="img"
            aria-labelledby="graph-title"
          >
            <title id="graph-title">
              ARIA&apos;s triage graph: plan, four parse workers, merge, severity and recall in
              parallel, investigate, assess (which can widen the search and investigate again),
              report, comms, human review, publish.
            </title>
            <g fill="none" strokeWidth="1.5" strokeLinecap="round">
              {EDGES.map(([a, b]) => {
                const from = BY_ID[a];
                const to = BY_ID[b];
                if (!from || !to) return null;
                return (
                  <path
                    key={`${a}-${b}`}
                    data-edge
                    data-target={b}
                    d={edgePath(from, to)}
                    className={cn(
                      "transition-colors duration-(--duration-moderate)",
                      lit.has(b) ? "stroke-foreground/70" : "stroke-control/60",
                    )}
                  />
                );
              })}
              <path
                d={WIDEN}
                strokeDasharray="4 4"
                className={cn(lit.has("assess") ? "stroke-primary" : "stroke-control/60")}
              />
            </g>
            <text x="324" y="400" className="fill-muted-foreground text-[11px]" textAnchor="middle">
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
                    rx={node.kind === "person" ? H / 2 : 4}
                    className={cn(
                      "transition-[fill,stroke] duration-(--duration-moderate)",
                      isCurrent
                        ? "fill-highlight stroke-primary"
                        : isLit
                          ? "fill-raised stroke-foreground/60"
                          : "fill-sunken stroke-control/70",
                    )}
                    strokeWidth={isCurrent ? 2 : 1}
                  />
                  <text
                    x={w / 2}
                    y={H / 2 + 4.5}
                    textAnchor="middle"
                    className={cn(
                      "font-mono text-[12px]",
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
