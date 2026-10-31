import { act, render, renderHook, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RunEvent } from "@/lib/api/types";

import {
  pacedSteps,
  progressSteps,
  reachedCount,
  type Step,
  Steps,
  usePacedSteps,
} from "./progress";

const event = (seq: number, kind: string, node: string | null, ts: string): RunEvent =>
  ({ seq, kind, node, ts, payload: {} }) as RunEvent;

const reading = [
  event(1, "node_started", "plan", "2026-10-01T00:00:00.000Z"),
  event(2, "node_finished", "plan", "2026-10-01T00:00:00.012Z"),
  event(3, "node_started", "parse_shard", "2026-10-01T00:00:00.012Z"),
  event(4, "node_finished", "parse_shard", "2026-10-01T00:00:00.040Z"),
  event(5, "node_started", "merge", "2026-10-01T00:00:00.040Z"),
  event(6, "node_finished", "merge", "2026-10-01T00:00:00.050Z"),
];

describe("progressSteps", () => {
  it("keeps a step at work between its parts, so its tick never comes and goes", () => {
    const written = [
      ...reading,
      event(7, "node_started", "report", "2026-10-01T00:00:00.060Z"),
      event(8, "node_finished", "report", "2026-10-01T00:00:00.070Z"),
    ];
    const write = (events: RunEvent[], status: string) =>
      progressSteps(events, status).find((s) => s.key === "write")?.state;
    expect(write(written, "running")).toBe("running");
    const reviewing = [
      ...written,
      event(9, "node_started", "comms", "2026-10-01T00:00:00.071Z"),
      event(10, "node_finished", "comms", "2026-10-01T00:00:00.080Z"),
      event(11, "node_started", "review", "2026-10-01T00:00:00.081Z"),
      event(12, "interrupt", "review", "2026-10-01T00:00:00.082Z"),
    ];
    expect(write(reviewing, "awaiting_review")).toBe("done");
  });

  it("names eight steps in plain words, each as far as its graph nodes got", () => {
    const steps = progressSteps(
      [
        ...reading,
        event(7, "node_started", "severity", "2026-10-01T00:00:00.050Z"),
        event(8, "node_started", "review", "2026-10-01T00:00:01.000Z"),
        event(9, "interrupt", "review", "2026-10-01T00:00:01.001Z"),
      ],
      "awaiting_review",
    );
    expect(steps.map((s) => s.label)).toEqual([
      "Read the logs",
      "Rate severity",
      "Find similar incidents",
      "Investigate",
      "Decide whether to look further",
      "Write the report",
      "Your review",
      "Publish",
    ]);
    expect(steps[0]).toMatchObject({ state: "done", took: 50 });
    expect(steps[1]?.state).toBe("running");
    expect(steps[6]?.state).toBe("paused");
    expect(steps[7]?.state).toBe("pending");
  });

  it("ends in Discard for a discarded draft, and marks steps a finished run never needed", () => {
    const steps = progressSteps(reading, "rejected");
    expect(steps.at(-1)).toMatchObject({ label: "Discard", state: "done" });
    expect(steps[3]?.state).toBe("skipped");
  });

  it("marks steps a run waiting for review passed without running as not needed", () => {
    const steps = progressSteps(
      [
        ...reading,
        event(7, "node_started", "report", "2026-10-01T00:00:00.060Z"),
        event(8, "node_finished", "report", "2026-10-01T00:00:00.070Z"),
        event(9, "node_started", "review", "2026-10-01T00:00:00.081Z"),
        event(10, "interrupt", "review", "2026-10-01T00:00:00.082Z"),
      ],
      "awaiting_review",
    );
    expect(steps.map((s) => s.state)).toEqual([
      "done",
      "skipped",
      "skipped",
      "skipped",
      "skipped",
      "done",
      "paused",
      "pending",
    ]);
  });

  it("counts the steps a copy carried over from its original as done there", () => {
    const steps = progressSteps(copied, "awaiting_review");
    expect(steps.map((s) => s.state)).toEqual([
      "done",
      "done",
      "done",
      "done",
      "done",
      "done",
      "paused",
      "pending",
    ]);
    expect(steps[0]).toMatchObject({ copied: true, note: "in the original", took: null });
    expect(steps[6]?.copied).toBeUndefined();
  });
});

// A copy of an incident that waited for review: it starts at the review, with nothing before it.
const copied = [
  {
    ...event(1, "run_started", null, "2026-10-01T00:00:00.000Z"),
    payload: { forked_from: "run-original", checkpoint_id: "c1" },
  },
  event(2, "node_started", "review", "2026-10-01T00:00:00.010Z"),
  event(3, "interrupt", "review", "2026-10-01T00:00:00.020Z"),
];

describe("usePacedSteps", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("finishes the playback of a copy, whose earlier steps it never ran", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(
      ({ events, status }: { events: RunEvent[]; status: string }) =>
        usePacedSteps("run-copy", events, status),
      { initialProps: { events: [] as RunEvent[], status: "running" } },
    );
    rerender({ events: copied, status: "awaiting_review" });
    // The carried-over steps show at once; only the review plays, then the strip holds and folds.
    expect(result.current.steps.slice(0, 6).every((s) => s.state === "done")).toBe(true);
    // Each step's timer is set once the one before it has rendered.
    for (const ms of [400, 1_100]) {
      act(() => {
        vi.advanceTimersByTime(ms);
      });
    }
    expect(result.current.playing).toBe(false);
    expect(result.current.steps[6]?.state).toBe("paused");
  });
});

describe("pacedSteps", () => {
  const finished: Step[] = [
    { key: "read", label: "Read the logs", state: "done", took: 40 },
    { key: "rate", label: "Rate severity", state: "done", took: 12 },
    { key: "recall", label: "Find similar incidents", state: "done", took: 30 },
    { key: "review", label: "Your review", state: "paused", took: null },
    { key: "publish", label: "Publish", state: "pending", took: null },
  ];

  it("counts the steps reached in order, up to the one that waits for a person", () => {
    expect(reachedCount(finished)).toBe(4);
    expect(reachedCount(finished.map((s) => ({ ...s, state: "done" as const })))).toBe(5);
  });

  it("plays a finished run back one step at a time", () => {
    expect(pacedSteps(finished, 0).map((s) => s.state)).toEqual([
      "running",
      "pending",
      "pending",
      "pending",
      "pending",
    ]);
    expect(pacedSteps(finished, 2).map((s) => s.state)).toEqual([
      "done",
      "done",
      "running",
      "pending",
      "pending",
    ]);
    // Once the playback has caught up, the steps are as they are.
    expect(pacedSteps(finished, 4)).toEqual(finished);
  });

  it("never shows a later step at work before the playback reaches it", () => {
    // A live run whose report is being written while the playback still shows the first step.
    const live: Step[] = [
      { key: "read", label: "Read the logs", state: "done", took: 40 },
      { key: "rate", label: "Rate severity", state: "done", took: 12 },
      { key: "write", label: "Write the report", state: "running", took: null },
      { key: "assess", label: "Decide", state: "done", took: 3, note: "looked further" },
    ];
    const shown = pacedSteps(live, 0);
    expect(shown.map((s) => s.state)).toEqual(["running", "pending", "pending", "pending"]);
    expect(shown[3]?.note).toBeUndefined();
  });
});

describe("Steps", () => {
  it("says each step's state to a screen reader", () => {
    render(<Steps steps={progressSteps(reading, "running")} />);
    const items = within(screen.getByRole("list", { name: "Run progress" })).getAllByRole(
      "listitem",
    );
    expect(items).toHaveLength(8);
    // The strip shows where a run is, not how long each step took (that is under "Every event").
    expect(items[0]?.textContent).toBe("Read the logs: done");
    expect(items[1]?.textContent).toBe("Rate severity: to come");
  });
});

describe("checkpoint names", () => {
  it("use the progress strip's step names", async () => {
    const { checkpointName: name } = await import("./history");
    expect(name({ next: ["severity", "recall"], interrupted: false })).toBe(
      "Before “Rate severity” and “Find similar incidents”",
    );
    expect(name({ next: ["parse_shard", "parse_shard", "parse_shard"], interrupted: false })).toBe(
      "During “Read the logs”: reading the lines (3 parts at once)",
    );
    expect(name({ next: ["review"], interrupted: true })).toBe("Paused at “Your review”");
  });

  it("tell apart two checkpoints inside one step", async () => {
    const { checkpointName: name } = await import("./history");
    expect(name({ next: ["report"], interrupted: false })).toBe("Before “Write the report”");
    expect(name({ next: ["comms"], interrupted: false })).toBe(
      "During “Write the report”: drafting the messages",
    );
  });

  it("never call a checkpoint inside a step one before it", async () => {
    const { checkpointName: name } = await import("./history");
    const labels = [["plan"], ["parse_shard"], ["merge"]].map((next) =>
      name({ next, interrupted: false }),
    );
    expect(labels).toEqual([
      "Before “Read the logs”",
      "During “Read the logs”: reading the lines",
      "During “Read the logs”: joining what was read",
    ]);
  });
});
