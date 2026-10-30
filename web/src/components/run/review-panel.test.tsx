import { describe, expect, it } from "vitest";

import { changedEdits, type EditForm } from "./review-panel";

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
