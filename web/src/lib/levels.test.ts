import { describe, expect, it } from "vitest";

import { orList, shortListText } from "./levels";

const assessment = (changes: Partial<Parameters<typeof shortListText>[0]> = {}) => ({
  severity: "SEV2" as const,
  prediction_set: ["SEV2" as const, "SEV3" as const],
  set_empty: false,
  decided_by: "fallback" as const,
  needs_review: true,
  ...changes,
});

describe("shortListText", () => {
  it("names the likely levels and the one ARIA plans for", () => {
    expect(shortListText(assessment())).toBe(
      "Could be SEV2 or SEV3. ARIA plans for SEV2. Please confirm.",
    );
    expect(
      shortListText(
        assessment({ prediction_set: ["SEV2"], decided_by: "model", needs_review: false }),
      ),
    ).toBe("Only SEV2 is likely, and the severity model is confident of it.");
    expect(
      shortListText(
        assessment({ prediction_set: ["SEV2"], decided_by: "rules", needs_review: false }),
      ),
    ).toBe("Only SEV2 is likely, and the rules agree.");
  });

  it("asks for a check when ARIA is unsure, even with one likely level", () => {
    expect(shortListText(assessment({ prediction_set: ["SEV2"] }))).toBe(
      "Probably SEV2. ARIA isn't sure enough to decide alone, so please confirm.",
    );
  });

  it("says why it asks: the model's figure, or the rules alone", () => {
    expect(shortListText(assessment({ prediction_set: ["SEV2"], confidence: 0.77 }))).toBe(
      "Probably SEV2, 77% likely. ARIA isn't sure enough to decide alone, so please confirm.",
    );
    expect(
      shortListText(
        assessment({ prediction_set: ["SEV2"], confidence: 0.95, model_version: "rules-only" }),
      ),
    ).toBe("Probably SEV2. Only ARIA's rules rated these logs, so please confirm.");
  });

  it("calls a level under half likely the likeliest, not probable", () => {
    expect(
      shortListText(assessment({ prediction_set: ["SEV1"], severity: "SEV1", confidence: 0.46 })),
    ).toBe(
      "SEV1 is the likeliest level, at 46%. ARIA isn't sure enough to decide alone, so please confirm.",
    );
  });

  it("says what came of the check once a person decided", () => {
    expect(shortListText(assessment({ prediction_set: ["SEV2"] }), "published")).toBe(
      "Probably SEV2. ARIA wasn't sure enough to decide alone. A reviewer confirmed it.",
    );
    expect(shortListText(assessment(), "published")).toBe(
      "Could be SEV2 or SEV3. ARIA planned for SEV2. A reviewer confirmed it.",
    );
    expect(shortListText(assessment(), "rejected")).toBe(
      "Could be SEV2 or SEV3. ARIA planned for SEV2.",
    );
  });

  it("says when no level was likely enough, or a rule or a reviewer set it", () => {
    expect(shortListText(assessment({ set_empty: true, prediction_set: ["SEV2", "SEV4"] }))).toBe(
      "No level was likely enough on its own, so SEV2 or SEV4 stay possible. ARIA plans for SEV2, the more serious. Please decide.",
    );
    expect(shortListText(assessment({ set_empty: true, prediction_set: ["SEV2"] }))).toBe(
      "No level was likely enough on its own. ARIA plans for SEV2, where the model and the rules meet. Please decide.",
    );
    expect(
      shortListText(
        assessment({ severity: "SEV1", prediction_set: ["SEV2"], decided_by: "rules" }),
      ),
    ).toBe("SEV2 is likely, but a safety rule keeps it at SEV1.");
    expect(shortListText(assessment({ severity: "SEV4", decided_by: "human" }))).toBe(
      "A reviewer set SEV4.",
    );
  });
});

describe("orList", () => {
  it("joins levels the way a sentence does", () => {
    expect(orList(["SEV1", "SEV2", "SEV3"])).toBe("SEV1, SEV2 or SEV3");
    expect(orList(["SEV2"])).toBe("SEV2");
  });
});
