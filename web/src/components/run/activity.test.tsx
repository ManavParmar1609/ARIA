import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RunEvent } from "@/lib/api/types";

import { GraphProgress } from "./activity";

const event = (seq: number, kind: string, node: string | null, ts: string): RunEvent =>
  ({ seq, kind, node, ts, payload: {} }) as RunEvent;

describe("GraphProgress", () => {
  it("shows every step, with timings for finished ones and the paused review", () => {
    const events = [
      event(1, "node_started", "plan", "2026-10-01T00:00:00.000Z"),
      event(2, "node_finished", "plan", "2026-10-01T00:00:00.012Z"),
      event(3, "node_started", "review", "2026-10-01T00:00:01.000Z"),
      event(4, "interrupt", "review", "2026-10-01T00:00:01.001Z"),
    ];
    render(<GraphProgress events={events} finalStatus="awaiting_review" />);
    const steps = within(screen.getByRole("list", { name: "Run progress" })).getAllByRole(
      "listitem",
    );
    const text = steps.map((s) => s.textContent);
    expect(text).toHaveLength(11);
    expect(text[0]).toBe("Plan12 ms: done");
    expect(text).toContain("Review: paused");
    expect(text).toContain("Report: pending");
  });

  it("ends in Reject for a rejected run", () => {
    render(<GraphProgress events={[]} finalStatus="rejected" />);
    const text = screen.getByRole("list", { name: "Run progress" }).textContent;
    expect(text).toContain("Reject: pending");
    expect(text).not.toContain("Publish");
  });
});
