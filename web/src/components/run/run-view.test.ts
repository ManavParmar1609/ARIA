import { describe, expect, it } from "vitest";

import type { SeverityAssessment } from "@/lib/api/types";
import { shortListText } from "@/lib/levels";

import { headerRating } from "./run-view";

const assessment = (changes: Partial<SeverityAssessment> = {}): SeverityAssessment => ({
  severity: "SEV1",
  decided_by: "fallback",
  rule_severity: "SEV1",
  rule_scores: {},
  rule_hits: [],
  probabilities: {},
  prediction_set: ["SEV1", "SEV2", "SEV3", "SEV4"],
  alpha: 0.1,
  floor: null,
  confidence: 0.3,
  auditable: true,
  needs_review: true,
  rationale: [],
  model_version: "severity-model-7",
  ...changes,
});

describe("the header's rating", () => {
  it("leads with the person a short list of every level waits for, and says the level as a plan", () => {
    expect(headerRating(assessment(), "awaiting_review")).toEqual({
      badge: "Not rated: needs a person",
      sentence: "Could be SEV1, SEV2, SEV3 or SEV4. ARIA plans for SEV1 until someone decides.",
    });
  });

  it("does so for three levels from the rules alone, but not from the calibrated model", () => {
    const three: SeverityAssessment["prediction_set"] = ["SEV1", "SEV2", "SEV3"];
    const rules = assessment({ prediction_set: three, model_version: "rules-only:2026.10" });
    expect(headerRating(rules, "awaiting_review").badge).toBe("Not rated: needs a person");
    const model = assessment({ prediction_set: three });
    expect(headerRating(model, "awaiting_review")).toEqual({
      badge: null,
      sentence: shortListText(model, "awaiting_review"),
    });
  });

  it("shows the level once a person has settled it, by setting it or approving the report", () => {
    expect(headerRating(assessment({ decided_by: "human" }), "awaiting_review").badge).toBeNull();
    expect(headerRating(assessment(), "published").badge).toBeNull();
  });

  it("calls a discarded draft's wide list not rated, without asking anyone", () => {
    expect(headerRating(assessment(), "rejected")).toEqual({
      badge: "Not rated",
      sentence: shortListText(assessment(), "rejected"),
    });
  });

  it("shows the level when ARIA decided alone", () => {
    expect(
      headerRating(assessment({ needs_review: false, decided_by: "rules" }), "awaiting_review")
        .badge,
    ).toBeNull();
  });
});
