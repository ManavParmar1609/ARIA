import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BlindCheck, DriftReport } from "./calibration-check";

const state = vi.hoisted(() => ({
  check: {
    isPending: false,
    isFetching: false,
    isError: false,
    error: null as unknown,
    data: null as unknown,
    refetch: vi.fn(),
  },
  rate: {
    mutateAsync: vi.fn(),
    reset: vi.fn(),
    isPending: false,
    isError: false,
  },
  drift: {
    isPending: false,
    isError: false,
    error: null as unknown,
    data: null as unknown,
    refetch: vi.fn(),
  },
}));
vi.mock("@/lib/api/hooks", () => ({
  useBlindCheck: () => state.check,
  useRateBlind: () => state.rate,
  useDrift: () => state.drift,
}));

const CASE = {
  run_id: "run-1",
  system: "bgl",
  lines: 1200,
  error_lines: 40,
  warning_lines: 3,
  nodes: 6,
  minutes: 20,
  patterns: [
    { template: "kernel panic on <*>", count: 40, error_like: true, new: true },
    { template: "heartbeat ok", count: 1157, error_like: false, new: false },
  ],
};

describe("a blind check", () => {
  beforeEach(() => {
    state.check.data = { case: CASE, checks: 2, counted: true };
    state.rate.mutateAsync.mockReset();
  });

  it("shows only what the logs held, then reveals ARIA's answer once rated", async () => {
    render(<BlindCheck />);
    fireEvent.click(screen.getByRole("button", { name: "Rate an incident blind" }));
    expect(screen.getByText("kernel panic on <*>")).toBeTruthy();
    // Nothing ARIA decided is on screen before the rating.
    expect(screen.queryByText(/ARIA said/)).toBeNull();
    state.rate.mutateAsync.mockResolvedValue({
      run_id: "run-1",
      yours: "SEV1",
      aria: "SEV2",
      prediction_set: ["SEV1", "SEV2"],
      held: true,
      agreed: false,
      counted: true,
      checks: 3,
    });
    fireEvent.click(screen.getByRole("button", { name: "SEV1 · critical" }));
    expect(await screen.findByText(/ARIA said SEV2 \(high\)/)).toBeTruthy();
    expect(screen.getByText("Your level was on its short list.")).toBeTruthy();
    expect(state.rate.mutateAsync).toHaveBeenCalledWith({ runId: "run-1", severity: "SEV1" });
  });

  it("says when nothing is left to rate", () => {
    state.check.data = { case: null, checks: 5, counted: true };
    render(<BlindCheck />);
    fireEvent.click(screen.getByRole("button", { name: "Rate an incident blind" }));
    expect(screen.getByText(/Nothing left to rate/)).toBeTruthy();
  });

  it("tells a demo visitor their ratings do not recalibrate ARIA", () => {
    state.check.data = { case: CASE, checks: 0, counted: false };
    render(<BlindCheck />);
    fireEvent.click(screen.getByRole("button", { name: "Rate an incident blind" }));
    expect(screen.getByText(/not used to recalibrate ARIA/)).toBeTruthy();
  });
});

describe("the drift report", () => {
  it("lists each compared system with its verdict", () => {
    state.drift.data = {
      min_runs: 40,
      systems: [
        {
          system: "hdfs",
          runs: 120,
          compared: 60,
          reference: { SEV4: 60 },
          recent: { SEV1: 30, SEV2: 30 },
          psi: 9.1,
          critical: 0.26,
          shifted: true,
        },
      ],
      too_few_runs: ["bgl", "zookeeper"],
    };
    render(<DriftReport />);
    expect(screen.getByText("Shifted beyond chance")).toBeTruthy();
    expect(screen.getByText(/Too few runs to compare yet: bgl and zookeeper/)).toBeTruthy();
  });

  it("explains the wait when no system has enough runs", () => {
    state.drift.data = { min_runs: 40, systems: [], too_few_runs: [] };
    render(<DriftReport />);
    expect(screen.getByText(/needs 40 decided runs/)).toBeTruthy();
  });
});
