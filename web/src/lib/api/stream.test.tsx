import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useRunTimeline } from "./stream";
import type { RunEvent } from "./types";

const event = (seq: number, kind: string, node: string | null = null): RunEvent =>
  ({ seq, kind, node, ts: "2026-10-01T00:00:00.000Z", payload: {} }) as RunEvent;

/** A stand-in for the browser's EventSource that the test feeds by hand. */
class FakeSource {
  static last: FakeSource | null = null;
  static readonly CLOSED = 2;
  readyState = 0;
  closed = false;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, (message: MessageEvent<string>) => void>();
  constructor(readonly url: string) {
    FakeSource.last = this;
  }
  addEventListener(kind: string, listener: (message: MessageEvent<string>) => void) {
    this.listeners.set(kind, listener);
  }
  send(e: RunEvent) {
    this.listeners.get(e.kind)?.({ data: JSON.stringify(e) } as MessageEvent<string>);
  }
  close() {
    this.closed = true;
    this.readyState = FakeSource.CLOSED;
  }
}

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
);

describe("useRunTimeline", () => {
  let stored: RunEvent[] = [];
  beforeEach(() => {
    FakeSource.last = null;
    vi.stubGlobal("EventSource", FakeSource);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json(stored)),
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("stops following a run when it pauses for review, so open tabs hold no connection", () => {
    const { result } = renderHook(() => useRunTimeline("run-1", "live", "running"), { wrapper });
    const source = FakeSource.last;
    expect(source?.url).toBe("/api/v1/runs/run-1/stream?until=review");
    act(() => {
      source?.send(event(1, "node_started", "plan"));
      source?.send(event(2, "interrupt", "review"));
    });
    expect(source?.closed).toBe(true);
    expect(result.current.events.map((e) => e.seq)).toEqual([1, 2]);
  });

  it("reads the rest once paused, and again after the decision, without repeating events", async () => {
    stored = [event(1, "node_started", "plan"), event(2, "interrupt", "review")];
    const { result, rerender } = renderHook(
      ({ mode, status }: { mode: "live" | "stored"; status: string }) =>
        useRunTimeline("run-1", mode, status),
      { wrapper, initialProps: { mode: "live", status: "running" } },
    );
    act(() => {
      FakeSource.last?.send(event(1, "node_started", "plan"));
      FakeSource.last?.send(event(2, "interrupt", "review"));
    });
    stored = [...stored, event(3, "budget")];
    rerender({ mode: "stored", status: "awaiting_review" });
    await waitFor(() => expect(result.current.events.map((e) => e.seq)).toEqual([1, 2, 3]));
    stored = [...stored, event(4, "review"), event(5, "run_finished")];
    rerender({ mode: "stored", status: "published" });
    await waitFor(() => expect(result.current.events.map((e) => e.seq)).toEqual([1, 2, 3, 4, 5]));
  });
});
