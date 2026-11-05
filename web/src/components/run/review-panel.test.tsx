import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { OutboundAction } from "@/lib/api/types";

import {
  ActionChoice,
  approveLabel,
  changedEdits,
  hasChanges,
  RemovedFromDraft,
  removedWords,
  severityAdvice,
  type EditForm,
} from "./review-panel";

const original = {
  title: "Block serve exceptions in HDFS",
  severity: "SEV3" as const,
  summary: ["Writes failed on two DataNodes.", "Reads kept working."],
};

const form = (changes: Partial<EditForm> = {}): EditForm => ({
  title: original.title,
  severity: original.severity,
  summary: original.summary.join("\n"),
  addActions: "",
  note: "",
  ...changes,
});

describe("changedEdits", () => {
  it("sends nothing for a form the reviewer did not change", () => {
    expect(changedEdits(form(), original)).toEqual({
      title: undefined,
      severity: undefined,
      summary: undefined,
      add_actions: [],
      note: undefined,
    });
  });

  it("ignores whitespace the reviewer added around unchanged text", () => {
    const edits = changedEdits(
      form({
        title: ` ${original.title} `,
        summary: "\n Writes failed on two DataNodes. \nReads kept working.\n",
      }),
      original,
    );
    expect(edits.title).toBeUndefined();
    expect(edits.summary).toBeUndefined();
  });

  it("sends only the fields the reviewer changed", () => {
    const edits = changedEdits(
      form({ severity: "SEV2", summary: "Writes failed on two DataNodes.\nReads slowed down." }),
      original,
    );
    expect(edits.title).toBeUndefined();
    expect(edits.severity).toBe("SEV2");
    expect(edits.summary).toEqual(["Writes failed on two DataNodes.", "Reads slowed down."]);
  });

  it("sends a new title, actions and a note", () => {
    const edits = changedEdits(
      form({
        title: "Disk failures on two DataNodes",
        addActions: "Replace the disks\n\n",
        note: " Checked by hand ",
      }),
      original,
    );
    expect(edits).toMatchObject({
      title: "Disk failures on two DataNodes",
      add_actions: ["Replace the disks"],
      note: "Checked by hand",
    });
  });
});

describe("hasChanges", () => {
  it("counts only what the server counts as a change", () => {
    expect(hasChanges(changedEdits(form(), original))).toBe(false);
    expect(hasChanges(changedEdits(form({ summary: "" }), original))).toBe(false); // keeps it
    expect(hasChanges(changedEdits(form({ severity: "SEV2" }), original))).toBe(true);
    expect(hasChanges(changedEdits(form({ note: "Checked" }), original))).toBe(true);
    expect(hasChanges(changedEdits(form({ addActions: "Page storage" }), original))).toBe(true);
  });
});

describe("approveLabel", () => {
  it("says send only when a message will go out", () => {
    expect(approveLabel(0, false)).toBe("Approve and publish");
    expect(approveLabel(2, false)).toBe("Approve and send");
    expect(approveLabel(2, true)).toBe("Saving");
  });
});

describe("removedWords", () => {
  it("counts links and recipients in plain words", () => {
    expect(removedWords(["link to evil[.]example"])).toBe("1 link not on the allow-list");
    expect(
      removedWords([
        "link to evil[.]example",
        "recipient @channel",
        "recipient ops@corp[.]example",
      ]),
    ).toBe("1 link not on the allow-list and 2 recipients nobody configured");
    expect(
      removedWords(["link to a javascript: target", "link to www[.]x[.]com", "something"]),
    ).toBe("2 links not on the allow-list and 1 other item");
    expect(removedWords([])).toBe("");
  });
});

const draft: OutboundAction = {
  action_id: "act-1",
  kind: "slack",
  audience: "responders",
  title: "[SEV2] Block serve exceptions in HDFS",
  body: "Apply the fix at [link removed] and ping [recipient removed].",
  status: "proposed",
  requires_approval: true,
  evidence_ids: ["E1"],
  removed: ["link to evil[.]example", "recipient @channel"],
};

describe("RemovedFromDraft", () => {
  it("says what was removed and lists each item, defanged", () => {
    render(<RemovedFromDraft removed={draft.removed} detailed />);
    expect(
      screen.getByText(
        "Removed from this draft: 1 link not on the allow-list and 1 recipient nobody configured.",
      ),
    ).toBeTruthy();
    expect(screen.getByText("link to evil[.]example")).toBeTruthy();
    expect(screen.getByText("recipient @channel")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("has an empty state, a loading state and an error state", () => {
    const empty = render(<RemovedFromDraft removed={[]} detailed />);
    expect(screen.getByText("Nothing was removed from this draft.")).toBeTruthy();
    empty.unmount();
    const loading = render(<RemovedFromDraft removed={undefined} state="loading" detailed />);
    expect(screen.getByRole("status").textContent).toContain("Checking what was removed");
    loading.unmount();
    render(<RemovedFromDraft removed={undefined} state="error" detailed />);
    expect(screen.getByRole("alert").textContent).toContain("could not load what was removed");
  });

  it("says nothing in the row when nothing was removed, or when the run never said", () => {
    const { container } = render(<RemovedFromDraft removed={[]} />);
    expect(container.textContent).toBe("");
    const unknown = render(<RemovedFromDraft removed={undefined} />);
    expect(unknown.container.textContent).toBe("");
  });
});

describe("ActionChoice", () => {
  it("names the removals in the message row, before the message is opened", () => {
    render(
      <ul>
        <ActionChoice action={draft} />
      </ul>,
    );
    expect(screen.getByText(/Removed from this draft: 1 link not on the allow-list/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Show the message" })).toBeTruthy();
  });

  it("shows a message that is still loading as such, with what was removed already known", () => {
    render(
      <ul>
        <ActionChoice action={{ ...draft, body: "" }} draftState="loading" />
      </ul>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Show the message" }));
    expect(screen.getByRole("status").textContent).toContain("Loading the message");
    expect(screen.getByText("link to evil[.]example")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Copy/ })).toBeNull(); // nothing to copy yet
  });

  it("says when a message could not be loaded", () => {
    render(
      <ul>
        <ActionChoice action={{ ...draft, body: "", removed: undefined }} draftState="error" />
      </ul>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Show the message" }));
    const alerts = screen.getAllByRole("alert").map((node) => node.textContent);
    expect(alerts.some((text) => text?.includes("The message could not be loaded"))).toBe(true);
    expect(alerts.some((text) => text?.includes("could not load what was removed"))).toBe(true);
  });
});

describe("severityAdvice", () => {
  const prompt = (changes: Partial<Parameters<typeof severityAdvice>[0]> = {}) => ({
    severity: "SEV2" as const,
    prediction_set: ["SEV2" as const, "SEV3" as const],
    needs_review: true,
    ...changes,
  });

  it("names the levels ARIA is torn between, not a bare level", () => {
    expect(severityAdvice(prompt())).toBe(
      "ARIA is torn between SEV2 and SEV3 and plans for SEV2. Check the severity before approving, or change it with Edit before sending.",
    );
    // Even when no one asked for a check, the review says the level is one of several.
    expect(severityAdvice(prompt({ needs_review: false }))).toBe(
      "ARIA is torn between SEV2 and SEV3 and plans for SEV2. Approving keeps SEV2; Edit before sending changes it.",
    );
  });

  it("keeps today's words for a set of one level", () => {
    expect(severityAdvice(prompt({ prediction_set: ["SEV2"] }))).toBe(
      "ARIA isn't sure enough of SEV2 to decide alone. Check the severity before approving, or change it with Edit before sending.",
    );
    expect(severityAdvice(prompt({ prediction_set: ["SEV2"], needs_review: false }))).toBeNull();
  });
});
