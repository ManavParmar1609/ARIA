"use client";

import {
  BotIcon,
  CircleCheckIcon,
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
import { capitalise, decisionWords, duration, reviewerName } from "@/lib/format";
import { cn } from "@/lib/utils";

import { NODE_LABEL } from "@/lib/steps";

import { Citations } from "./evidence";

type StepState = "pending" | "running" | "done" | "paused" | "failed";

export function stepStates(events: RunEvent[]) {
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

const MESSAGE_OUTCOME: Record<string, string> = {
  sent: "Sent",
  failed: "Not delivered",
  skipped: "Kept as a preview (no channel connected)",
  approved: "Sending",
};

function rows(events: RunEvent[], { offline = false, titles = {} }: RowOptions = {}): Row[] {
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
          detail: `${offline ? "" : `${Number(p.llm_calls ?? 0)} model calls, `}${Number(p.tool_calls ?? 0)} tool calls${Array.isArray(p.exhausted) && p.exhausted.length ? `; budget exhausted: ${(p.exhausted as string[]).join(", ")}` : ""}`,
          tone: Array.isArray(p.exhausted) && p.exhausted.length ? "warn" : undefined,
        });
        break;
      case "review":
        out.push({
          key,
          t,
          icon: FlagIcon,
          tone: "accent",
          title: `${capitalise(decisionWords(String(p.decision)))} by ${reviewerName(typeof p.reviewer === "string" ? p.reviewer : null)}`,
        });
        break;
      case "action":
        out.push({
          key,
          t,
          icon: SendIcon,
          tone: p.status === "failed" ? "bad" : p.status === "sent" ? "good" : undefined,
          title: `${MESSAGE_OUTCOME[String(p.status)] ?? String(p.status)}${p.resent_by ? ` (sent again by ${String(p.resent_by)})` : ""}: ${titles[String(p.action_id)] ?? "a message"}`,
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
interface RowOptions {
  /** The offline stand-in served the run: its calls are not model use. */
  offline?: boolean;
  /** Message titles by action id, so a message reads as what it says, not its id. */
  titles?: Record<string, string>;
}

export function Activity({ events, offline, titles }: { events: RunEvent[] } & RowOptions) {
  const list = useMemo(() => rows(events, { offline, titles }), [events, offline, titles]);
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
              transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
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
