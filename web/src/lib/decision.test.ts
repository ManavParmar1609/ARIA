import { describe, expect, it } from "vitest";

import { decidedByLabel, decisionPhrase } from "./decision";

const base = { severity: "SEV3", prediction_set: ["SEV3"] };

describe("decisionPhrase", () => {
  it("names who settled it when a rule, the model or a reviewer did", () => {
    expect(decisionPhrase({ ...base, decided_by: "rules" })).toBe(
      "Set by the rules, and the model agrees.",
    );
    expect(decisionPhrase({ ...base, decided_by: "model" })).toBe(
      "Confident: decided by the model.",
    );
    expect(decisionPhrase({ ...base, decided_by: "human" })).toBe(
      "A reviewer chose SEV3 from the short list.",
    );
    // A reviewer may go outside the list; the page says so rather than show a list without it.
    expect(decisionPhrase({ ...base, severity: "SEV2", decided_by: "human" })).toBe(
      "A reviewer set SEV2, outside ARIA's short list.",
    );
  });

  it("asks a person to confirm one likely level the model was not sure of", () => {
    // The landing page's recorded run: one level, but not confident enough to decide alone.
    expect(decisionPhrase({ ...base, decided_by: "fallback" })).toBe(
      "Only SEV3 is on the short list, but ARIA was not sure enough of it to decide alone. Please confirm.",
    );
    // Once a person has reviewed it, the page says what came of the request.
    expect(decisionPhrase({ ...base, decided_by: "fallback" }, "published")).toBe(
      "Only SEV3 is on the short list, but ARIA was not sure enough of it to decide alone. A reviewer confirmed it.",
    );
    expect(decisionPhrase({ ...base, decided_by: "fallback" }, "rejected")).toBe(
      "Only SEV3 is on the short list, but ARIA was not sure enough of it to decide alone.",
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
