import { describe, expect, it } from "vitest";

import { logsHint } from "./new-run";

describe("logsHint", () => {
  it("says how pasted lines are protected", () => {
    expect(logsHint(null, false)).toContain("secrets redacted");
  });

  it("warns on a public demo that every visitor can open the runs", () => {
    expect(logsHint(null, true)).toContain("public demo: anyone can open the runs");
  });

  it("names what is wrong with the lines first", () => {
    expect(logsHint("Paste at least one log line, or load a sample.", true)).toBe(
      "Paste at least one log line, or load a sample.",
    );
  });
});
