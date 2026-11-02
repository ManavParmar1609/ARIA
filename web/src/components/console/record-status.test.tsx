import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ChainCheckView } from "@/lib/api/hooks";

import { RecordStatus, recordWords } from "./record-status";

const state = vi.hoisted(() => ({
  check: {
    isPending: false,
    isError: false,
    error: null as unknown,
    data: null as unknown,
    refetch: vi.fn(),
  },
}));
vi.mock("@/lib/api/hooks", () => ({ useAuditVerify: () => state.check }));

const HASH = "b".repeat(64);
const HOLDS: ChainCheckView = {
  ok: true,
  length: 42,
  first_broken: null,
  problem: null,
  head_hash: HASH,
  checked_at: "2026-10-29T07:41:12Z",
};
const BROKEN: ChainCheckView = {
  ok: false,
  length: 17,
  first_broken: 17,
  problem: "entry 17 does not match its own hash",
  head_hash: null,
  checked_at: "2026-10-29T07:41:12Z",
};

describe("whether the record verifies, in words", () => {
  it("says how long a sound chain is, and where a broken one breaks", () => {
    expect(recordWords(HOLDS)).toBe(
      "The decision record holds 42 entries, and every link in its chain verifies.",
    );
    expect(recordWords({ ...HOLDS, length: 1 })).toBe(
      "The decision record holds one entry, and every link in its chain verifies.",
    );
    expect(recordWords({ ...HOLDS, length: 0, head_hash: null })).toBe(
      "The decision record is empty: nothing has been decided yet.",
    );
    expect(recordWords(BROKEN)).toBe(
      "The decision record is broken at entry 17: entry 17 does not match its own hash. " +
        "Treat that as a sign of tampering, and follow the ops runbook.",
    );
  });
});

describe("the record status line", () => {
  beforeEach(() => {
    Object.assign(state.check, { isPending: false, isError: false, error: null, data: HOLDS });
    state.check.refetch.mockReset();
  });

  it("shows the verdict, when it was checked and the newest hash to keep elsewhere", () => {
    render(<RecordStatus />);
    expect(screen.getByRole("status").textContent).toBe(recordWords(HOLDS));
    expect(screen.getByText(HASH)).toBeTruthy();
    expect(screen.getByText(/^Checked /)).toBeTruthy();
  });

  it("marks a broken chain as a warning", () => {
    state.check.data = BROKEN;
    render(<RecordStatus />);
    const line = screen.getByRole("status");
    expect(line.textContent).toContain("broken at entry 17");
    expect(line.className).toContain("text-danger");
    expect(screen.queryByText(/Newest hash/)).toBeNull();
  });

  it("shows that it is checking, and a failure with a way to try again", () => {
    state.check.isPending = true;
    const { unmount } = render(<RecordStatus />);
    expect(screen.getByText("Checking the decision record")).toBeTruthy();
    unmount();
    Object.assign(state.check, { isPending: false, isError: true, error: new Error("down") });
    render(<RecordStatus />);
    expect(screen.getByRole("alert").textContent).toContain("could not be checked");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(state.check.refetch).toHaveBeenCalled();
  });
});
