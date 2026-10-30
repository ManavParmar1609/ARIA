import { describe, expect, it } from "vitest";

import { count, duration, median, money, percent, relativeTime, stripSeverity } from "./format";

describe("format", () => {
  it("writes durations a person can read", () => {
    expect(duration(734)).toBe("734 ms");
    expect(duration(2_240)).toBe("2.2 s");
    expect(duration(42_000)).toBe("42 s");
    expect(duration(193_000)).toBe("3 min 13 s");
    expect(duration(null)).toBe("");
  });

  it("writes relative times against a fixed clock", () => {
    const now = Date.parse("2026-10-29T08:00:00Z");
    expect(relativeTime("2026-10-29T07:59:50Z", now)).toBe("just now");
    expect(relativeTime("2026-10-29T07:57:00Z", now)).toBe("3 minutes ago");
    expect(relativeTime("2026-10-28T08:00:00Z", now)).toBe("yesterday");
    expect(relativeTime(undefined, now)).toBe("");
  });

  it("formats percentages, money and medians", () => {
    expect(percent(0.9033, 1)).toBe("90.3%");
    expect(percent(undefined)).toBe("");
    expect(money(0)).toBe("$0");
    expect(money(0.004)).toBe("$0.0040");
    expect(money(1.5)).toBe("$1.50");
    expect(median([3, 1, 2])).toBe(2);
    expect(median([4, 1, 2, 3])).toBe(2.5);
    expect(median([])).toBeNull();
  });

  it("drops the severity prefix report titles carry", () => {
    expect(stripSeverity("SEV3 · Block serve exceptions in HDFS")).toBe(
      "Block serve exceptions in HDFS",
    );
    expect(stripSeverity("Kernel panics")).toBe("Kernel panics");
    expect(stripSeverity(null)).toBe("");
  });
});

describe("count", () => {
  it("spells counts below ten and writes digits from ten on", () => {
    expect(count(0)).toBe("no");
    expect(count(6)).toBe("six");
    expect(count(10)).toBe("10");
    expect(count(5247088)).toBe("5,247,088");
  });
});
