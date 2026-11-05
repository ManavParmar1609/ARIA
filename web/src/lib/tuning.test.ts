import { describe, expect, it } from "vitest";

import evals from "@/data/eval-results.json";
import { registry } from "@/test/domains";

import { readTuning, ringTuning, tuningLabel, tuningTitle, type TuningRecord } from "./tuning";

const record = () => readTuning(registry()) as TuningRecord;

describe("the tuning record", () => {
  it("reads nothing when the results have no record yet", () => {
    expect(readTuning(undefined)).toBeNull();
    expect(readTuning({ suites: {} })).toBeNull();
    expect(readTuning({ suites: { bgl: { ring: "C", status: "peeked" } } })).toBeNull();
  });

  it("reads each test's ring, status, date and note", () => {
    expect(record()["real.hadoop"]).toEqual({
      suite: "real.hadoop",
      ring: "C",
      status: "tuned",
      since: "2026-11-01",
      note: "A rule changed after these jobs.",
    });
    expect(record()["real.hdfs"]?.since).toBeNull();
  });

  it("says each status as its badge shows it", () => {
    expect(tuningLabel({ status: "untouched", since: null })).toBe("Untouched");
    expect(tuningLabel({ status: "seen", since: "2026-11-01" })).toBe("Looked at");
    expect(tuningLabel({ status: "tuned", since: "2026-11-01" })).toBe("Tuned since 2026-11-01");
    expect(tuningLabel({ status: "tuned", since: null })).toBe("Tuned");
    // The card a badge opens gives the record's date whatever the status.
    expect(tuningTitle({ status: "seen", since: "2026-11-01" })).toBe("Looked at since 2026-11-01");
    expect(tuningTitle({ status: "seen", since: null })).toBe("Looked at");
  });

  it("gives a group of one test that test's own record", () => {
    expect(ringTuning(record(), "A")).toEqual({
      status: "tuned",
      since: null,
      note: "Fresh windows of the training systems.",
    });
    expect(ringTuning(record(), "B")?.since).toBe("2026-11-01");
    expect(ringTuning(record(), "D")).toBeNull();
  });

  it("gives a larger group the badge of its least clean test, and counts the rest", () => {
    const real = ringTuning(record(), "C", { "real.hadoop": "Hadoop jobs" });
    expect(real?.status).toBe("tuned");
    expect(real?.since).toBe("2026-11-01");
    expect(real?.note).toBe(
      "The badge shows the least clean test in this group. Of the 5 tests in this group, 4 were looked at and 1 was tuned. Tuned: Hadoop jobs (since 2026-11-01).",
    );
    const seen = readTuning({
      suites: {
        a: { ring: "C", status: "seen", since: "2026-11-02" },
        b: { ring: "C", status: "seen", since: "2026-10-30" },
      },
    }) as TuningRecord;
    expect(ringTuning(seen, "C")).toMatchObject({ status: "seen", since: "2026-10-30" });
    expect(ringTuning(seen, "C")?.note).toContain("All 2 tests in this group were looked at.");
  });

  const published = (evals as unknown as Record<string, unknown>).registry as
    { suites?: Record<string, unknown> } | undefined;

  it.skipIf(!published)("reads every entry of the published record", () => {
    expect(Object.keys(readTuning(published) ?? {})).toEqual(Object.keys(published?.suites ?? {}));
  });
});
