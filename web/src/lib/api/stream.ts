"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { apiFetch } from "./client";
import { keys } from "./hooks";
import type { RunEvent } from "./types";

const KINDS = [
  "run_started",
  "node_started",
  "node_finished",
  "token",
  "tool_call",
  "llm_call",
  "replan",
  "budget",
  "guardrail",
  "interrupt",
  "review",
  "action",
  "run_finished",
  "checkpoint",
  "error",
] as const;

/** Events after which the run's detail, state and report are worth fetching again. */
const REFRESH_ON = new Set(["node_finished", "interrupt", "review", "action", "run_finished"]);

export type StreamState = "connecting" | "live" | "reconnecting" | "replayed" | "closed" | "error";

export interface Timeline {
  events: RunEvent[];
  /** Model output streaming right now, by graph node (tokens are never stored). */
  liveText: Record<string, string>;
  state: StreamState;
}

interface Held extends Timeline {
  key: string;
}

const empty = (key: string): Held => ({ key, events: [], liveText: {}, state: "connecting" });

/**
 * A run's events. A finished run is read once over REST; a live one over server-sent events,
 * which replay what is stored and then follow the run (EventSource resumes from the last event id
 * after a dropped connection, so nothing is missed or repeated).
 */
export function useRunTimeline(runId: string, mode: "live" | "stored" | "off"): Timeline {
  const client = useQueryClient();
  const live = mode === "live";
  const key = `${runId}:${mode}`;
  const [held, setHeld] = useState<Held>(() => empty(key));
  const refreshTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (mode === "off") return;
    let cancelled = false;
    const seen = new Set<number>();
    // Updates for this run only; a stale callback from a previous run starts from empty.
    const update = (change: (current: Held) => Held) =>
      setHeld((current) => change(current.key === key ? current : empty(key)));

    const refresh = () => {
      window.clearTimeout(refreshTimer.current);
      refreshTimer.current = window.setTimeout(() => {
        void client.invalidateQueries({ queryKey: keys.run(runId) });
        void client.invalidateQueries({ queryKey: ["runs"] });
      }, 250);
    };

    const add = (incoming: RunEvent[]) => {
      const fresh = incoming.filter((e) => e.kind !== "token" && !seen.has(e.seq));
      if (fresh.length === 0) return;
      for (const e of fresh) seen.add(e.seq);
      const finishedNodes = new Set(
        fresh.filter((e) => e.kind === "node_finished").map((e) => e.node ?? ""),
      );
      update((current) => {
        const liveText = { ...current.liveText };
        for (const node of finishedNodes) delete liveText[node];
        const events = [...current.events, ...fresh].sort((a, b) => a.seq - b.seq);
        return { ...current, events, liveText };
      });
      if (fresh.some((e) => REFRESH_ON.has(e.kind))) refresh();
    };

    if (!live) {
      apiFetch<RunEvent[]>(`/api/v1/runs/${encodeURIComponent(runId)}/events?limit=5000`)
        .then((stored) => {
          if (cancelled) return;
          add(stored);
          update((current) => ({ ...current, state: "replayed" }));
        })
        .catch(() => {
          if (!cancelled) update((current) => ({ ...current, state: "error" }));
        });
      return () => {
        cancelled = true;
      };
    }

    const source = new EventSource(`/api/v1/runs/${encodeURIComponent(runId)}/stream`);
    let finished = false;
    source.onopen = () => update((current) => ({ ...current, state: "live" }));
    source.onerror = () => {
      if (finished || source.readyState === EventSource.CLOSED) {
        source.close();
        update((current) => ({ ...current, state: finished ? "closed" : "error" }));
      } else {
        update((current) => ({ ...current, state: "reconnecting" }));
      }
    };
    const onEvent = (message: MessageEvent<string>) => {
      let event: RunEvent;
      try {
        event = JSON.parse(message.data) as RunEvent;
      } catch {
        return;
      }
      if (event.kind === "token") {
        // The report writer streams {text} chunks, and {reset} when it restarts an attempt.
        const node = event.node ?? "report";
        const payload = event.payload ?? {};
        const chunk = typeof payload.text === "string" ? payload.text : "";
        if (payload.reset === true || chunk) {
          update((current) => ({
            ...current,
            liveText: {
              ...current.liveText,
              [node]: payload.reset === true ? "" : (current.liveText[node] ?? "") + chunk,
            },
          }));
        }
        return;
      }
      add([event]);
      if (event.kind === "run_finished") {
        finished = true;
        source.close();
        update((current) => ({ ...current, state: "closed" }));
      }
    };
    for (const kind of KINDS) source.addEventListener(kind, onEvent as EventListener);
    return () => {
      cancelled = true;
      window.clearTimeout(refreshTimer.current);
      source.close();
    };
  }, [client, key, runId, live, mode]);

  const current = held.key === key ? held : empty(key);
  return { events: current.events, liveText: current.liveText, state: current.state };
}
