import { describe, expect, it } from "vitest";

import { logsHint, modelHint } from "./new-run";

describe("logsHint", () => {
  it("says how pasted lines are protected", () => {
    expect(logsHint(null, false)).toContain("secrets redacted");
  });

  it("says on a public demo that only the visitor sees the incident, on a shared server", () => {
    const hint = logsHint(null, true);
    expect(hint).toContain("only you see it");
    expect(hint).toContain("shared server");
  });

  it("names what is wrong with the lines first", () => {
    const problem = "Paste at least one log line, or pick a sample on the Samples tab.";
    expect(logsHint(problem, true)).toBe(problem);
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
