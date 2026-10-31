import { describe, expect, it } from "vitest";

import { decidedByLabel, decisionPhrase } from "./decision";

const base = { severity: "SEV3", prediction_set: ["SEV3"] };

describe("decisionPhrase", () => {
  it("names who settled it when a rule, the model or a reviewer did", () => {
    expect(decisionPhrase({ ...base, decided_by: "rules" })).toBe("Set by a rule.");
    expect(decisionPhrase({ ...base, decided_by: "model" })).toBe(
      "Confident: decided by the model.",
    );
    expect(decisionPhrase({ ...base, decided_by: "human" })).toBe("Set by a reviewer.");
  });

  it("asks a person to confirm one likely level the model was not sure of", () => {
    // The landing page's recorded run: one level, but not confident enough to decide alone.
    expect(decisionPhrase({ ...base, decided_by: "fallback" })).toBe(
      "Probably SEV3, but ARIA is not sure enough to decide alone. Please confirm.",
    );
  });

  it("lists the levels still possible, most serious first, and plans for the worst", () => {
    expect(
      decisionPhrase({
        severity: "SEV2",
        decided_by: "fallback",
        prediction_set: ["SEV3", "SEV2"],
      }),
    ).toBe("Could be SEV2 or SEV3. ARIA plans for SEV2, the most serious of them. Please confirm.");
    expect(
      decisionPhrase({
        severity: "SEV3",
        decided_by: "llm",
        prediction_set: ["SEV2", "SEV3", "SEV4"],
      }),
    ).toBe("Could be SEV2, SEV3 or SEV4. A language model chose SEV3 from that list.");
  });

  it("says when no level was likely enough", () => {
    expect(decisionPhrase({ ...base, decided_by: "fallback", set_empty: true })).toBe(
      "No level was likely enough, so ARIA plans for SEV3. Please decide.",
    );
  });

  it("gives lists a few plain words", () => {
    expect(decidedByLabel("fallback")).toBe("Needs your call");
    expect(decidedByLabel(null)).toBe("");
    expect(decidedByLabel("something-new")).toBe("something-new");
  });
});
