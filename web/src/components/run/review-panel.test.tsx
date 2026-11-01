import { describe, expect, it } from "vitest";

import {
  approveLabel,
  changedEdits,
  hasChanges,
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
