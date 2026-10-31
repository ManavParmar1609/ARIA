import { describe, expect, it } from "vitest";

import { evaluation, realData, realLogs } from "@/lib/site-data";

import {
  alarmsAnswer,
  bglVerdict,
  buildsVerdict,
  decidingVerdict,
  elsewhereLines,
  endToEndVerdict,
  gitlabVerdict,
  hadoopVerdict,
  hdfsVerdict,
  heldAsPromised,
  injectionVerdict,
  inTen,
  liveVerdict,
  memoryAnswer,
  openstackVerdict,
  postmortemsVerdict,
  readingVerdict,
  resultsInShort,
  severityVerdict,
  shortfallLines,
  ticketsVerdict,
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
        { name: "BlueGene/L", value: 0.06 },
      ],
      0.9,
    );
    expect(answer).toBe(
      "On built samples, yes: its short list of likely levels held the right one about as often as promised, 90 times in 100. On BlueGene/L, no: there the list held the right level only 6 times in 100, so ARIA was confidently wrong.",
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
    // Whichever way it goes, the answer opens with a verdict.
    expect(alarmsAnswer(fair)).toMatch(/^Mostly, though it still misses some\./);
    expect(bglVerdict(fair)).toContain("its own rules alone strike a different balance");
    expect(bglVerdict(bgl)).toBe(
      "On a real supercomputer, ARIA misses about 1 in 10 serious problems and raises false alarms on about 1 in 10 quiet stretches; its own rules alone would have done better.",
    );
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

describe("what each test result means for the person on call", () => {
  it("says a share as a newcomer reads it", () => {
    expect(inTen(0)).toBe("no");
    expect(inTen(0.04)).toBe("fewer than 1 in 10");
    expect(inTen(0.41)).toBe("about 4 in 10");
    expect(inTen(0.97)).toBe("nearly all");
    expect(inTen(1)).toBe("all");
  });

  it("opens every result card with one plain sentence, written from the published results", () => {
    const data = evaluation();
    const real = realLogs();
    const more = realData();
    const verdicts = [
      hdfsVerdict(real),
      bglVerdict(more.bgl),
      hadoopVerdict(more),
      openstackVerdict(more),
      buildsVerdict(more),
      ticketsVerdict(more),
      gitlabVerdict(more),
      postmortemsVerdict(more),
      injectionVerdict(more),
      severityVerdict(data),
      decidingVerdict(data),
      endToEndVerdict(data),
      readingVerdict(data),
      liveVerdict(data),
      resultsInShort(data, real),
    ];
    for (const verdict of verdicts) {
      expect(verdict).not.toMatch(/undefined|NaN|null|Infinity/);
      // One sentence: a capital first, one full stop, at the end.
      expect(verdict).toMatch(/^[A-Z][^.]*[^.\s]\.$/);
    }
  });

  it("reads a match with the best standard detector as the match it is", () => {
    const real = realLogs();
    const best = [...real.detectors].sort(
      (a, b) => b.recall - a.recall || a.falseAlarms - b.falseAlarms,
    )[0];
    const same = {
      ...real,
      lifecycle: { ...real.lifecycle, flagged: 100, falseAlarms: 2, precision: 0.98, recall: 0.6 },
      detectors: [{ ...best, flagged: 100, falseAlarms: 2 }],
    } as typeof real;
    expect(hdfsVerdict(same)).toBe(
      "When ARIA flags a block, it is almost always failing, but it misses about 4 in 10 failures; the best standard detector, which needs experts to prepare the log first, does no better.",
    );
    const beaten = {
      ...same,
      detectors: [{ ...best, flagged: 120, falseAlarms: 2 }],
    } as typeof real;
    expect(hdfsVerdict(beaten)).toMatch(/does better\.$/);
    expect(resultsInShort(evaluation(), beaten)).toContain(
      "on a real cluster, though not as well as the best standard detector,",
    );
  });

  it("reads well when a share is nothing at all", () => {
    const more = realData();
    const perfect = {
      ...more.bgl,
      aria: { ...more.bgl.aria, severeMissed: 0, quietPaged: 0 },
      rules: { ...more.bgl.rules, severeMissed: 3, quietPaged: 9 },
    } as typeof more.bgl;
    expect(bglVerdict(perfect)).toBe(
      "On a real supercomputer, ARIA misses no serious problems and raises no false alarms; that beats its own rules alone.",
    );
    expect(alarmsAnswer(perfect)).toMatch(/^Yes\. /);
  });

  it("says plainly when a test finds ARIA's flags no use", () => {
    const more = realData();
    const all = {
      ...more,
      openstack: {
        ...more.openstack,
        aria: {
          ...more.openstack.aria,
          caught: 99,
          failed: 100,
          recall: 0.99,
          falseAlarms: 50,
          healthy: 50,
        },
      },
    } as typeof more;
    expect(openstackVerdict(all)).toContain("so on this cloud its flags can't yet tell you");
    const calm = {
      ...more,
      openstack: {
        ...more.openstack,
        aria: {
          ...more.openstack.aria,
          caught: 99,
          failed: 100,
          recall: 0.99,
          falseAlarms: 1,
          healthy: 50,
        },
      },
    } as typeof more;
    expect(openstackVerdict(calm)).not.toContain("but");
  });
});
