import { describe, expect, it } from "vitest";

import type { ParsedBatch, TemplateStat } from "@/lib/api/types";

import { leadingPatterns, scaleSentence } from "./what-happened";

const features = (changes: Partial<ParsedBatch["features"]> = {}) =>
  ({
    n_events: 125,
    duration_s: 462,
    level_counts: { INFO: 65, FATAL: 60 },
    error_events: 60,
    error_nodes: 2,
    distinct_nodes: 48,
    ...changes,
  }) as ParsedBatch["features"];

const template = (
  id: string,
  count: number,
  changes: Partial<TemplateStat> = {},
): TemplateStat => ({
  template_id: id,
  template: `pattern ${id}`,
  count,
  levels: { INFO: count },
  nodes: 1,
  first_ts: null,
  last_ts: null,
  error_like: false,
  novel: false,
  components: [],
  sample_idx: [],
  evidence_id: `E${id}`,
  ...changes,
});

describe("scaleSentence", () => {
  it("says how much, over how long, and where the errors were", () => {
    expect(scaleSentence(features())).toBe(
      "125 lines over 7.7 minutes: 60 errors, on 2 of 48 servers.",
    );
  });

  it("says a short window's lines came within a minute", () => {
    expect(scaleSentence(features({ n_events: 40, duration_s: 12 }))).toBe(
      "40 lines within a minute: 60 errors, on 2 of 48 servers.",
    );
    expect(scaleSentence(features({ n_events: 40, duration_s: 60 }))).toMatch(
      /^40 lines over 1 minute:/,
    );
  });

  it("says when there were no errors", () => {
    expect(
      scaleSentence(features({ error_events: 0, level_counts: { INFO: 100, WARN: 25 } })),
    ).toBe("125 lines over 7.7 minutes: no errors, but 25 warnings.");
    expect(scaleSentence(features({ error_events: 0, level_counts: { INFO: 125 } }))).toBe(
      "125 lines over 7.7 minutes: no errors or warnings.",
    );
  });
});

describe("leadingPatterns", () => {
  it("puts error-like and new patterns before merely frequent ones", () => {
    const leading = leadingPatterns([
      template("a", 900),
      template("b", 12, { error_like: true }),
      template("c", 40, { novel: true }),
      template("d", 300),
    ]);
    expect(leading.map((t) => t.template_id)).toEqual(["b", "c", "a"]);
  });
});
