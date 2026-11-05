import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DecisionRecordEntry } from "@/lib/api/hooks";

import { byWhom, DecisionRecord, whatHappened } from "./decision-record";

const state = vi.hoisted(() => ({
  record: {
    isPending: false,
    isError: false,
    error: null as unknown,
    data: null as unknown,
    refetch: vi.fn(),
  },
}));
vi.mock("@/lib/api/hooks", () => ({ useRunRecord: () => state.record }));

const HASH = "a".repeat(64);

const entry = (
  seq: number,
  kind: DecisionRecordEntry["kind"],
  actor: string,
  payload: Record<string, unknown>,
): DecisionRecordEntry => ({
  seq,
  ts: `2026-10-29T07:41:${String(10 + seq).padStart(2, "0")}Z`,
  kind,
  run_id: "run-1",
  actor,
  payload,
  prev_hash: HASH,
  hash: HASH,
});

const ENTRIES: DecisionRecordEntry[] = [
  entry(0, "blind_check", "raj", { to: "SEV2", aria: "SEV3", held: false }),
  entry(1, "review", "ana", {
    decision: "edit",
    from_severity: "SEV3",
    to_severity: "SEV2",
    approved_actions: ["act-1"],
  }),
  entry(2, "edit", "ana", { severity: "SEV2", summary_lines: 2, actions_added: 1, note: "x" }),
  entry(3, "publish", "ana", { version: 2, valid: true }),
  entry(4, "send", "ana", { channel: "slack", audience: "stakeholders", status: "sent" }),
  entry(5, "send", "ben", {
    channel: "webhook",
    audience: "customers",
    status: "failed",
    problem: "HTTP 503",
    resent: true,
  }),
];

describe("what happened, in words", () => {
  it("says what each kind of entry did", () => {
    expect(ENTRIES.map(whatHappened)).toEqual([
      "Rated the incident blind at SEV2; ARIA said SEV3, outside its short list.",
      "Edited and approved the report, SEV3 to SEV2, and approved one message.",
      "Changed the level to SEV2, the summary, one action and a note.",
      "Published the report, version 2.",
      "Sent the stakeholders update through Slack.",
      "Could not deliver the customers update again through the outbound webhook: HTTP 503.",
    ]);
    expect(
      whatHappened(entry(6, "review", "ana", { decision: "approve", to_severity: "SEV1" })),
    ).toBe("Approved the report at SEV1.");
    expect(whatHappened(entry(7, "review", "ana", { decision: "reject" }))).toBe(
      "Discarded the report.",
    );
    expect(whatHappened(entry(8, "edit", "ana", {}))).toBe("Edited the report.");
    expect(whatHappened(entry(9, "publish", "system", { version: 1, valid: false }))).toBe(
      "Published the report, with validation warnings.",
    );
    expect(whatHappened(entry(10, "send", "ana", { channel: "teams", status: "skipped" }))).toBe(
      "Kept the responders update as a preview: Teams is not connected.",
    );
    expect(whatHappened(entry(11, "recalibration", "system", { model_version: "m-aci12" }))).toBe(
      "Recalibrated the severity model to m-aci12.",
    );
    expect(whatHappened(entry(12, "model_swap", "system", { model_version: "m-aci12" }))).toBe(
      "Started using severity model m-aci12.",
    );
    expect(whatHappened(entry(13, "purge", "system", { days: 30 }))).toBe(
      "Purged the incident after 30 days without a change.",
    );
    expect(whatHappened(entry(14, "delete", "ana", {}))).toBe("Deleted the incident.");
  });

  it("names who decided as a person reads it", () => {
    expect(byWhom("ana")).toBe("By ana");
    expect(byWhom("system")).toBe("By ARIA");
    expect(byWhom("cli")).toBe("By the operator, from the command line");
    expect(byWhom("anonymous")).toBe("By a reviewer");
  });
});

describe("the decision record card", () => {
  beforeEach(() => {
    Object.assign(state.record, { isPending: false, isError: false, error: null, data: ENTRIES });
    state.record.refetch.mockReset();
  });

  it("lists each decision with its time, what happened and who did it", () => {
    render(<DecisionRecord runId="run-1" />);
    const card = screen.getByRole("region", { name: "Decision record" });
    const items = within(card).getAllByRole("listitem");
    expect(items).toHaveLength(ENTRIES.length);
    const first = items[0]!;
    expect(within(first).getByText(/07:41:10/)).toBeTruthy();
    expect(within(first).getByText(/^Rated the incident blind/)).toBeTruthy();
    expect(within(first).getByText("By raj")).toBeTruthy();
    expect(within(items[5]!).getByText("By ben")).toBeTruthy();
  });

  it("shows nothing until someone has decided, so an empty card never pushes the report down", () => {
    state.record.data = [];
    const { container } = render(<DecisionRecord runId="run-1" />);
    expect(container.innerHTML).toBe("");
    expect(screen.queryByRole("region", { name: "Decision record" })).toBeNull();
  });

  it("shows that it is loading, and a failure with a way to try again", () => {
    state.record.isPending = true;
    const { unmount } = render(<DecisionRecord runId="run-1" />);
    expect(screen.getByText("Loading the decision record")).toBeTruthy();
    unmount();
    Object.assign(state.record, { isPending: false, isError: true, error: new Error("down") });
    render(<DecisionRecord runId="run-1" />);
    expect(screen.getByRole("alert").textContent).toContain("could not be loaded");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(state.record.refetch).toHaveBeenCalled();
  });
});
