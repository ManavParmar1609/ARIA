import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { readFrom, ReviewerStats, share } from "./reviewer-stats";

const state = vi.hoisted(() => ({
  reviewers: {
    isPending: false,
    isError: false,
    error: null as unknown,
    data: null as unknown,
    refetch: vi.fn(),
  },
}));
vi.mock("@/lib/api/hooks", () => ({ useReviewers: () => state.reviewers }));

const VIEW = {
  decisions: 5,
  limit: 2000,
  since: "2026-10-01T09:00:45Z",
  reviewers: [
    {
      reviewer: "ana",
      decisions: 4,
      approved_as_is: 3,
      edited: 1,
      rejected: 0,
      level_changed: 1,
      timed: 4,
      median_wait_s: 372,
    },
    {
      reviewer: "anonymous",
      decisions: 1,
      approved_as_is: 0,
      edited: 0,
      rejected: 1,
      level_changed: 0,
      timed: 0,
      median_wait_s: null,
    },
  ],
};

describe("how each reviewer decides", () => {
  beforeEach(() => {
    Object.assign(state.reviewers, { isPending: false, isError: false, error: null, data: VIEW });
    state.reviewers.refetch.mockReset();
  });

  it("shows each reviewer's approvals, changed levels and median time to decide", () => {
    render(<ReviewerStats />);
    const table = screen.getByRole("table", { name: "How each reviewer decides" });
    const [, ana, nobody] = within(table).getAllByRole("row");
    expect(
      within(ana!)
        .getAllByRole("cell")
        .map((c) => c.textContent),
    ).toEqual(["4", "3 of 4 (75%)", "1 of 4 (25%)", "6 min 12 s"]);
    // A review made without a key reads as "a reviewer", and an unknown time says so.
    expect(within(nobody!).getByRole("rowheader").textContent).toBe("A reviewer");
    expect(within(nobody!).getByText("Not known")).toBeTruthy();
    expect(screen.getByText(/^From the five reviews ARIA keeps, since /)).toBeTruthy();
  });

  it("says when there are no reviews yet", () => {
    state.reviewers.data = { ...VIEW, decisions: 0, since: null, reviewers: [] };
    render(<ReviewerStats />);
    expect(screen.getByText(/^No reviews yet\./)).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("shows that it is loading, and a failure with a way to try again", () => {
    state.reviewers.isPending = true;
    const { unmount } = render(<ReviewerStats />);
    expect(screen.getByText("Loading how each reviewer decides")).toBeTruthy();
    unmount();
    Object.assign(state.reviewers, { isPending: false, isError: true, error: new Error("down") });
    render(<ReviewerStats />);
    expect(screen.getByRole("alert").textContent).toContain("could not be loaded");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(state.reviewers.refetch).toHaveBeenCalled();
  });
});

describe("share and readFrom", () => {
  it("put a count beside its share, and say which reviews the figures come from", () => {
    expect(share(1, 3)).toBe("1 of 3 (33%)");
    expect(share(0, 0)).toBe("");
    expect(readFrom({ decisions: 1, limit: 2000, since: null })).toBe(
      "From the one review ARIA keeps.",
    );
    expect(readFrom({ decisions: 2000, limit: 2000, since: null })).toBe(
      "From the 2,000 most recent reviews ARIA keeps.",
    );
  });
});
