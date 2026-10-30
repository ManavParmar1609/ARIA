"use client";

import {
  BotIcon,
  CircleCheckIcon,
  CircleDotIcon,
  CircleIcon,
  FlagIcon,
  GaugeIcon,
  OctagonAlertIcon,
  PlayIcon,
  RefreshCwIcon,
  SendIcon,
  ShieldAlertIcon,
  UserRoundCheckIcon,
  WrenchIcon,
  type LucideIcon,
} from "lucide-react";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useMemo } from "react";

import type { RunEvent } from "@/lib/api/types";
import { duration } from "@/lib/format";
import { cn } from "@/lib/utils";

import { NODE_LABEL } from "@/lib/steps";

import { Citations } from "./evidence";

const PATH = [
  "plan",
  "parse_shard",
  "merge",
  "severity",
  "recall",
  "investigate",
  "assess",
  "report",
  "comms",
  "review",
  "publish",
];

type StepState = "pending" | "running" | "done" | "paused" | "failed";

function stepStates(events: RunEvent[]) {
  const state: Record<string, StepState> = {};
  const started: Record<string, number> = {};
  const took: Record<string, number> = {};
  for (const e of events) {
    const node = e.node ?? "";
    const t = new Date(e.ts ?? 0).getTime();
    if (e.kind === "node_started") {
      state[node] = "running";
      started[node] = t;
    } else if (e.kind === "node_finished") {
      state[node] = "done";
      if (started[node] != null) took[node] = (took[node] ?? 0) + (t - (started[node] ?? t));
    } else if (e.kind === "interrupt") {
      state[node] = "paused";
    } else if (e.kind === "error" && node) {
      state[node] = "failed";
    }
  }
  return { state, took };
}

/**
 * Where the run is in the graph: each step done, running, paused for review or still to come.
 * Steps sit in equal cells, so the layout does not move when timings arrive.
 */
export function GraphProgress({
  events,
  finalStatus,
}: {
  events: RunEvent[];
  finalStatus: string;
}) {
  const { state, took } = useMemo(() => stepStates(events), [events]);
  const path = finalStatus === "rejected" ? [...PATH.slice(0, -1), "reject"] : PATH;
  const replanned = events.some((e) => e.kind === "replan");
  return (
    <ol
      aria-label="Run progress"
      className="grid grid-cols-2 gap-1.5 min-[25rem]:grid-cols-3 sm:grid-cols-4 lg:grid-cols-6"
    >
      {path.map((node) => {
        const s = state[node] ?? "pending";
        return (
          <li
            key={node}
            className={cn(
              "flex h-8 min-w-0 items-center gap-1.5 rounded-xs border px-2 text-xs",
              s === "done" && "border-rule text-foreground",
              s === "running" && "border-primary bg-highlight text-highlight-foreground",
              s === "paused" && "border-primary bg-highlight font-medium text-highlight-foreground",
              s === "failed" && "border-danger text-danger",
              s === "pending" && "border-dashed border-rule text-faint",
            )}
          >
            {s === "done" ? (
              <CircleCheckIcon aria-hidden className="size-3 shrink-0 text-ok" />
            ) : s === "running" ? (
              <CircleDotIcon
                aria-hidden
                className="size-3 shrink-0 animate-pulse motion-reduce:animate-none"
              />
            ) : s === "paused" ? (
              <UserRoundCheckIcon aria-hidden className="size-3 shrink-0" />
            ) : s === "failed" ? (
              <OctagonAlertIcon aria-hidden className="size-3 shrink-0" />
            ) : (
              <CircleIcon aria-hidden className="size-3 shrink-0" />
            )}
            <span className="truncate">{NODE_LABEL[node] ?? node}</span>
            {node === "assess" && replanned ? (
              <RefreshCwIcon aria-label="replanned" className="size-3 shrink-0" />
            ) : null}
            {took[node] != null && s === "done" ? (
              <span className="tabular ml-auto hidden shrink-0 text-faint sm:inline">
                {duration(took[node])}
              </span>
            ) : null}
            <span className="sr-only">: {s}</span>
          </li>
        );
      })}
    </ol>
  );
}

interface Row {
  key: string;
  t: number;
  icon: LucideIcon;
  tone?: "warn" | "bad" | "good" | "accent";
  title: string;
  detail?: string;
  evidence?: string[];
  node?: string | null;
}

function rows(events: RunEvent[]): Row[] {
  const start = events[0] ? new Date(events[0].ts ?? 0).getTime() : 0;
  const tools = new Map<string, RunEvent>();
  const out: Row[] = [];
  for (const e of events) {
    const t = new Date(e.ts ?? 0).getTime() - start;
    const p = (e.payload ?? {}) as Record<string, unknown>;
    const label = NODE_LABEL[e.node ?? ""] ?? e.node ?? "";
    const key = `${e.seq}`;
    switch (e.kind) {
      case "run_started":
        out.push({
          key,
          t,
          icon: PlayIcon,
          title: "Run started",
          detail: p.trigger ? `trigger: ${String(p.trigger)}` : undefined,
        });
        break;
      case "node_finished": {
        const notes = Array.isArray(p.notes) ? (p.notes as string[]).join("; ") : undefined;
        out.push({
          key,
          t,
          icon: CircleCheckIcon,
          tone: "good",
          title: `${label} finished`,
          detail: notes,
          node: e.node,
        });
        break;
      }
      case "tool_call":
        if (p.phase === "start") {
          tools.set(String(p.ref), e);
        } else {
          const args = { ...((p.arguments as Record<string, unknown>) ?? {}) };
          delete args.run_id;
          out.push({
            key,
            t,
            icon: WrenchIcon,
            tone: p.ok === false ? "bad" : undefined,
            title: `${String(p.tool)}(${Object.entries(args)
              .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
              .join(", ")})`,
            detail: typeof p.summary === "string" ? p.summary : undefined,
            evidence: Array.isArray(p.evidence_ids) ? (p.evidence_ids as string[]) : undefined,
            node: e.node,
          });
        }
        break;
      case "llm_call":
        out.push({
          key,
          t,
          icon: BotIcon,
          title: `${String(p.task ?? "model call")} on ${String(p.provider ?? "")}${p.model ? ` (${String(p.model)})` : ""}`,
          detail: `${duration(Number(p.latency_ms ?? 0))}, ${Number(p.input_tokens ?? 0).toLocaleString("en")} tokens in, ${Number(p.output_tokens ?? 0).toLocaleString("en")} out${p.error ? `; failed: ${String(p.error)}` : ""}`,
          tone: p.error ? "bad" : undefined,
          node: e.node,
        });
        break;
      case "guardrail":
        out.push({
          key,
          t,
          icon: ShieldAlertIcon,
          tone: "warn",
          title: `Guardrail: ${Number(p.quarantined ?? 0)} line${Number(p.quarantined) === 1 ? "" : "s"} quarantined as possible prompt injection`,
          node: e.node,
        });
        break;
      case "replan":
        out.push({
          key,
          t,
          icon: RefreshCwIcon,
          tone: "accent",
          title: `Replanned (${Number(p.replans ?? 1)}): widening the search`,
          detail: Array.isArray(p.reasons) ? (p.reasons as string[]).join("; ") : undefined,
        });
        break;
      case "interrupt":
        out.push({
          key,
          t,
          icon: UserRoundCheckIcon,
          tone: "accent",
          title: "Paused for human review",
          detail: p.error ? `Last decision was refused: ${String(p.error)}` : undefined,
        });
        break;
      case "budget":
        out.push({
          key,
          t,
          icon: GaugeIcon,
          title: `Ready for review after ${duration(Number(p.latency_ms ?? 0))}`,
          detail: `${Number(p.llm_calls ?? 0)} model calls, ${Number(p.tool_calls ?? 0)} tool calls${Array.isArray(p.exhausted) && p.exhausted.length ? `; budget exhausted: ${(p.exhausted as string[]).join(", ")}` : ""}`,
          tone: Array.isArray(p.exhausted) && p.exhausted.length ? "warn" : undefined,
        });
        break;
      case "review":
        out.push({
          key,
          t,
          icon: FlagIcon,
          tone: "accent",
          title: `Review: ${String(p.decision)} by ${String(p.reviewer ?? "a reviewer")}`,
        });
        break;
      case "action":
        out.push({
          key,
          t,
          icon: SendIcon,
          tone: p.status === "failed" ? "bad" : "good",
          title: `Message ${String(p.action_id)}: ${String(p.status)}`,
        });
        break;
      case "error":
        out.push({
          key,
          t,
          icon: OctagonAlertIcon,
          tone: "bad",
          title: `Error${e.node ? ` in ${label}` : ""}`,
          detail: String(p.error ?? ""),
        });
        break;
      case "run_finished":
        out.push({
          key,
          t,
          icon: FlagIcon,
          tone: p.status === "failed" ? "bad" : "good",
          title: `Run finished: ${String(p.status)}`,
        });
        break;
      default:
        break;
    }
  }
  return out;
}

const TONE: Record<string, string> = {
  warn: "text-sev3-fg",
  bad: "text-danger",
  good: "text-ok",
  accent: "text-primary",
};

/** Everything the agents did, in order, from the run's event stream. */
export function Activity({ events }: { events: RunEvent[] }) {
  const list = useMemo(() => rows(events), [events]);
  if (list.length === 0) return <p className="text-sm text-muted-foreground">No activity yet.</p>;
  // Rows present on first render stay put; rows that arrive while the run is live slide in.
  return (
    <ol className="grid">
      <AnimatePresence initial={false}>
        {list.map((row) => {
          const Icon = row.icon;
          return (
            <m.li
              key={row.key}
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.22, ease: [0.25, 1, 0.5, 1] }}
              className="grid grid-cols-[4.5rem_1.25rem_minmax(0,1fr)] gap-3 border-b border-rule/60 py-2.5 text-sm last:border-0"
            >
              <span className="tabular pt-0.5 text-right font-mono text-xs text-faint">
                +{duration(row.t)}
              </span>
              <Icon
                aria-hidden
                className={cn("mt-0.5 size-4", row.tone ? TONE[row.tone] : "text-faint")}
              />
              <div className="grid min-w-0 gap-0.5">
                <p className={cn("wrap-anywhere", row.icon === WrenchIcon && "font-mono text-xs")}>
                  {row.title}
                </p>
                {row.detail ? (
                  <p className="text-xs wrap-anywhere text-muted-foreground">{row.detail}</p>
                ) : null}
                {row.evidence?.length ? <Citations ids={row.evidence} className="mt-1" /> : null}
              </div>
            </m.li>
          );
        })}
      </AnimatePresence>
    </ol>
  );
}
