import { describe, expect, it } from "vitest";

import { generalisation, newDomains, realData, testedOn, testedOnText } from "@/lib/site-data";

describe("what the site says it was tested on", () => {
  it("counts the real datasets on Test results, the HDFS log included", () => {
    const tested = testedOn();
    const real = Object.keys(realData()).length + 1;
    expect(tested.datasets).toBe(real + (newDomains()?.results.length ?? 0));
    expect(tested.datasets).toBeGreaterThanOrEqual(real);
  });

  it("names the tests on systems the model never saw only once the results hold them", () => {
    expect(testedOn().unseen).toBe(generalisation() != null);
    expect(testedOnText({ datasets: 9, unseen: false })).toBe(
      "ARIA is tested on 9 public, labelled datasets, each against a simpler method.",
    );
    expect(testedOnText({ datasets: 9, unseen: true })).toContain(
      "on systems its model never saw, each held out in turn",
    );
  });
});
