import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SeverityAssessment } from "@/lib/api/types";

import { SeverityPanel } from "./severity-panel";

const assessment = (changes: Partial<SeverityAssessment> = {}): SeverityAssessment => ({
  severity: "SEV2",
  decided_by: "fallback",
  rule_severity: "SEV2",
  rule_scores: { SEV2: 1.5, SEV3: 1 },
  rule_hits: [],
  probabilities: { SEV1: 0.05, SEV2: 0.45, SEV3: 0.4, SEV4: 0.1 },
  prediction_set: ["SEV2", "SEV3"],
  alpha: 0.1,
  floor: null,
  confidence: 0.45,
  auditable: true,
  needs_review: true,
  rationale: [],
  model_version: "log-v3",
  ...changes,
});

/** The sentence under the level stamp: what the level means, and how settled it is. */
const meaning = () => screen.getByText(/Usual response:/).textContent;

describe("the severity panel", () => {
  it("says which levels ARIA is torn between instead of a bare level", () => {
    render(<SeverityPanel assessment={assessment()} status="awaiting_review" />);
    expect(meaning()).toBe(
      "ARIA is torn between SEV2 and SEV3 and plans for SEV2. Major degradation or a failing critical part. Usual response: page the on-call team.",
    );
  });

  it("says what ARIA had planned once a reviewer approved it", () => {
    render(<SeverityPanel assessment={assessment()} status="published" />);
    expect(meaning()).toMatch(/^ARIA was torn between SEV2 and SEV3 and planned for SEV2\. /);
  });

  it("names every level of a wide set it could not narrow down", () => {
    render(
      <SeverityPanel
        assessment={assessment({
          severity: "SEV1",
          prediction_set: ["SEV1", "SEV2", "SEV3", "SEV4"],
        })}
        status="awaiting_review"
      />,
    );
    expect(meaning()).toMatch(
      /^Not settled: ARIA is torn between SEV1, SEV2, SEV3 and SEV4 and plans for SEV1 until someone decides\. /,
    );
  });

  it("keeps the level's own words for a set of one level, or a reviewer's level", () => {
    const { unmount } = render(
      <SeverityPanel
        assessment={assessment({ prediction_set: ["SEV2"], decided_by: "model" })}
        status="awaiting_review"
      />,
    );
    expect(meaning()).toBe(
      "Major degradation or a failing critical part. Usual response: page the on-call team.",
    );
    unmount();
    render(
      <SeverityPanel
        assessment={assessment({ severity: "SEV3", decided_by: "human" })}
        status="published"
      />,
    );
    expect(meaning()).toBe(
      "A contained problem with limited user impact. Usual response: fix it during working hours.",
    );
  });
});
