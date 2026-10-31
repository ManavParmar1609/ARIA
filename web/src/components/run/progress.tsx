"use client";

import {
  CheckIcon,
  ChevronRightIcon,
  CircleAlertIcon,
  CircleCheckIcon,
  UserRoundIcon,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, type CSSProperties } from "react";

import type { RunEvent } from "@/lib/api/types";
import { duration } from "@/lib/format";
import { cn } from "@/lib/utils";

import { stepStates } from "./activity";

// Where a run is, in eight steps with plain names (item 17). A line traces through the finished
// steps once, when the strip comes into view: a quick pass from the first step to the last, by
// transform alone, and simply there under reduced motion (A). Once the run has finished, the
// strip folds into one line saying how long ARIA took.

export type StepState = "pending" | "running" | "done" | "paused" | "failed" | "skipped";

export interface Step {
  key: string;
  label: string;
  state: StepState;
  took: number | null;
  note?: string;
}

const STEPS: { key: string; label: string; nodes: string[] }[] = [
  { key: "read", label: "Read the logs", nodes: ["plan", "parse_shard", "merge"] },
  { key: "rate", label: "Rate severity", nodes: ["severity"] },
  { key: "recall", label: "Find similar incidents", nodes: ["recall", "widen"] },
  { key: "investigate", label: "Investigate", nodes: ["investigate"] },
  { key: "assess", label: "Decide whether to look further", nodes: ["assess"] },
  { key: "write", label: "Write the report", nodes: ["report", "comms"] },
  { key: "review", label: "Your review", nodes: ["review"] },
  { key: "publish", label: "Publish", nodes: ["publish"] },
];

/** The step a graph node belongs to, by the name the progress strip gives it. */
export function stepLabel(node: string): string {
  if (node === "reject") return "Discard";
  return STEPS.find((step) => step.nodes.includes(node))?.label ?? node;
}

const ENDED = new Set(["published", "rejected", "failed"]);

/** Each step's state from the run's events: the worst of its graph nodes, and what it took. */
export function progressSteps(events: RunEvent[], status: string): Step[] {
  const { state, took } = stepStates(events);
  const replanned = events.some((e) => e.kind === "replan");
  const steps = STEPS.map(({ key, label, nodes }): Step => {
    const states = nodes.map((n) => state[n]).filter(Boolean);
    const stepState: StepState = states.includes("failed")
      ? "failed"
      : states.includes("running")
        ? "running"
        : states.includes("paused")
          ? "paused"
          : states.includes("done")
            ? "done"
            : "pending";
    const times = nodes.map((n) => took[n]).filter((t): t is number => t != null);
    return {
      key,
      label,
      state: stepState,
      took: times.length ? times.reduce((a, b) => a + b, 0) : null,
      note: key === "assess" && replanned ? "looked further" : undefined,
    };
  });
  if (status === "rejected") {
    steps[steps.length - 1] = { key: "discard", label: "Discard", state: "done", took: null };
  }
  // A finished run's steps that never ran were not needed (investigating can be switched off).
  return ENDED.has(status)
    ? steps.map((s) => (s.state === "pending" ? { ...s, state: "skipped" } : s))
    : steps;
}

const ICON: Partial<Record<StepState, LucideIcon>> = {
  done: CheckIcon,
  paused: UserRoundIcon,
  failed: CircleAlertIcon,
};

const STATE_WORDS: Record<StepState, string> = {
  pending: "to come",
  running: "running",
  done: "done",
  paused: "waiting for you",
  failed: "failed",
  skipped: "not needed",
};

/** Mark the list once it is on screen, so the trace plays then, once; then drop the stagger. */
function useTrace<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let settle: ReturnType<typeof setTimeout> | undefined;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry?.isIntersecting) return;
        el.setAttribute("data-traced", "");
        // Steps that finish later draw their part at once, without the first pass's stagger.
        settle = setTimeout(() => el.setAttribute("data-settled", ""), 1_200);
        observer.disconnect();
      },
      { threshold: 0.4 },
    );
    observer.observe(el);
    return () => {
      observer.disconnect();
      clearTimeout(settle);
    };
  }, []);
  return ref;
}

export function Steps({ steps }: { steps: Step[] }) {
  const ref = useTrace<HTMLOListElement>();
  return (
    <ol ref={ref} aria-label="Run progress" className="group grid gap-0 md:grid-cols-8 md:gap-x-0">
      {steps.map((step, i) => {
        const Icon = ICON[step.state];
        const last = i === steps.length - 1;
        return (
          <li
            key={step.key}
            className="relative flex gap-3 pb-4 last:pb-0 md:grid md:content-start md:gap-2 md:pr-2 md:pb-0"
            style={{ "--i": i } as CSSProperties}
          >
            {last ? null : (
              <span
                aria-hidden
                className="absolute top-6 bottom-0 left-2.5 w-0.5 -translate-x-1/2 bg-rule md:top-2.5 md:right-0 md:bottom-auto md:left-6 md:h-0.5 md:w-auto md:translate-x-0 md:-translate-y-1/2"
              >
                {step.state === "done" ? (
                  <span className="block size-full origin-top scale-y-0 bg-foreground transition-[scale] delay-[calc(var(--i)*110ms)] duration-300 ease-(--ease-out) group-data-settled:delay-0 group-data-traced:scale-y-100 motion-reduce:transition-none md:origin-left md:scale-x-0 md:scale-y-100 md:group-data-traced:scale-x-100" />
                ) : null}
              </span>
            )}
            <span
              className={cn(
                "relative z-10 grid size-5 shrink-0 place-items-center rounded-full border text-[0.625rem]",
                step.state === "done" && "border-foreground bg-foreground text-background",
                step.state === "running" && "border-primary bg-background",
                step.state === "paused" && "border-primary bg-highlight text-highlight-foreground",
                step.state === "failed" && "border-danger bg-danger text-background",
                step.state === "pending" && "border-rule bg-background",
                step.state === "skipped" && "border-dashed border-rule bg-background",
              )}
            >
              {Icon ? <Icon aria-hidden className="size-3" strokeWidth={2.5} /> : null}
              {step.state === "running" ? (
                <span
                  aria-hidden
                  className="block size-2 rounded-full bg-primary motion-safe:animate-pulse"
                />
              ) : null}
            </span>
            <span className="grid min-w-0 gap-0.5 pt-px md:pt-0">
              <span
                className={cn(
                  "text-sm leading-snug md:text-xs",
                  (step.state === "pending" || step.state === "skipped") && "text-faint",
                  step.state === "paused" && "font-medium",
                )}
              >
                {step.label}
              </span>
              {step.note ? <span className="text-xs text-faint">{step.note}</span> : null}
              <span className="sr-only">: {STATE_WORDS[step.state]}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/** The run's progress: the strip while it works, one folded line once it has finished. */
export function RunProgress({
  events,
  status,
  latencyMs,
  facts,
}: {
  events: RunEvent[];
  status: string;
  /** How long ARIA took to have the report ready. */
  latencyMs: number | null | undefined;
  /** Model and tool use, in words ("offline: no language model, 3 tool calls"). */
  facts: string;
}) {
  const steps = useMemo(() => progressSteps(events, status), [events, status]);
  if (status === "published" || status === "rejected") {
    return (
      <details className="group/progress rounded-lg bg-raised px-5 py-3">
        <summary className="flex cursor-pointer flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          <CircleCheckIcon aria-hidden className="size-4 text-ok" />
          <span className="font-medium">
            {latencyMs != null ? `ARIA finished in ${duration(latencyMs)}` : "ARIA finished"}
          </span>
          <span className="text-muted-foreground">{facts}</span>
          <ChevronRightIcon
            aria-hidden
            className="size-4 text-muted-foreground transition-transform duration-(--duration-quick) group-open/progress:rotate-90 motion-reduce:transition-none"
          />
        </summary>
        <div className="pt-4 pb-2">
          <Steps steps={steps} />
        </div>
      </details>
    );
  }
  return (
    <section aria-label="Progress" className="grid gap-3 rounded-lg bg-raised p-5">
      <Steps steps={steps} />
      {facts && status !== "queued" && status !== "running" ? (
        <p className="text-xs text-muted-foreground">{facts}</p>
      ) : null}
    </section>
  );
}
