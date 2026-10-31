import { describe, expect, it } from "vitest";

import { evaluation, realData, realLogs } from "@/lib/site-data";

import {
  alarmsAnswer,
  elsewhereLines,
  heldAsPromised,
  memoryAnswer,
  shortfallLines,
  unsureAnswer,
} from "./test-questions";

describe("the four questions on Test results", () => {
  it("calls a short list as promised only within 3 in 100 of the target", () => {
    expect(heldAsPromised(0.88, 0.9)).toBe(true);
    expect(heldAsPromised(0.86, 0.9)).toBe(false);
  });

  it("says yes and no in the right places when one log falls short", () => {
    const answer = unsureAnswer(
      [
        { name: "Built samples", phrase: "built samples", value: 0.91 },
        { name: "BlueGene/L", value: 0.89 },
        { name: "Thunderbird", value: 0.06 },
      ],
      0.9,
    );
    expect(answer).toBe(
      "On built samples and BlueGene/L, yes: its short list of likely levels held the right one about as often as promised, 90 times in 100. On Thunderbird, no: there the list held the right level only 6 times in 100, so ARIA was confidently wrong.",
    );
    expect(unsureAnswer([{ name: "A", value: 0.95 }], 0.9)).toMatch(/^Yes\./);
  });

  it("credits ARIA's own rules only when they miss and alarm less", () => {
    const method = (severeMissed: number, quietPaged: number, accuracy = 0.8) => ({
      accuracy,
      accuracyCi: [accuracy, accuracy],
      macroF1: 0.5,
      severeMissed,
      quietPaged,
      recall: {},
    });
    const bgl = {
      severe: 100,
      quiet: 900,
      aria: method(10, 50),
      rules: method(5, 40),
      majority: method(100, 0, 0.9),
    } as unknown as Parameters<typeof alarmsAnswer>[0];
    expect(alarmsAnswer(bgl)).toMatch(/^Not yet as well as it should\./);
    expect(alarmsAnswer(bgl)).toContain("did better on both: 5 missed and 40 false alarms");
    expect(alarmsAnswer(bgl)).toContain("Always answering “quiet” is right more often");
    const fair = { ...bgl, rules: method(20, 40) } as typeof bgl;
    expect(alarmsAnswer(fair)).not.toContain("did better");
  });

  it("writes every sentence from the published results without a gap", () => {
    const more = realData();
    const sentences = [
      alarmsAnswer(more.bgl),
      memoryAnswer(more),
      ...elsewhereLines(realLogs(), more),
      ...shortfallLines(evaluation(), more),
      unsureAnswer(
        [{ name: "Built samples", value: evaluation().severity.coverageWithFloors }],
        0.9,
      ),
    ];
    for (const sentence of sentences) {
      expect(sentence).not.toMatch(/undefined|NaN|null/);
      expect(sentence.trim()).toMatch(/[.]$/);
    }
  });
});
