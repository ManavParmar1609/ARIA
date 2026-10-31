import { describe, expect, it } from "vitest";

import { evidenceTitle } from "./evidence";

describe("an evidence title", () => {
  it("reads a pattern as lines like it, with its changing parts as ellipses", () => {
    expect(evidenceTitle({ kind: "template", title: "16x Failed password for <*> port <*>" })).toBe(
      "16 lines like “Failed password for … port …”",
    );
    expect(evidenceTitle({ kind: "template", title: "1x POSSIBLE BREAK-IN ATTEMPT <*>" })).toBe(
      "1 line: “POSSIBLE BREAK-IN ATTEMPT …”",
    );
  });

  it("leaves every other kind as recorded", () => {
    expect(evidenceTitle({ kind: "rule", title: "Rule R1 (score SEV2): 12x errors" })).toBe(
      "Rule R1 (score SEV2): 12x errors",
    );
  });
});
