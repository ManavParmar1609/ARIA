import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RunEvent } from "@/lib/api/types";

import { progressSteps, Steps } from "./progress";

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
      "Before “Read the logs” (3 parts at once)",
    );
    expect(name({ next: ["review"], interrupted: true })).toBe("Paused at “Your review”");
  });

  it("tell apart two checkpoints inside one step", async () => {
    const { checkpointName: name } = await import("./history");
    expect(name({ next: ["report"], interrupted: false })).toBe(
      "Before “Write the report”: the report itself",
    );
    expect(name({ next: ["comms"], interrupted: false })).toBe(
      "Before “Write the report”: the message drafts",
    );
  });
});
