import { describe, expect, it } from "vitest";

import { logsHint, modelHint } from "./new-run";

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

describe("modelHint", () => {
  it("says the visitor's own key answers first once one is saved", () => {
    expect(modelHint(["claude", "gemini"], "claude")).toContain(
      "your own Claude key answers first",
    );
  });

  it("points to Settings where visitors may bring a key", () => {
    expect(modelHint(["gemini"], null)).toContain("add your own key in Settings");
    expect(modelHint(["gemini"], "openai")).toContain("add your own key in Settings");
  });

  it("keeps the offline promise where no keys are taken", () => {
    expect(modelHint([], null)).toContain("nothing leaves the server");
  });
});
