import { describe, expect, it } from "vitest";

import { waitingText } from "@/lib/queue";

describe("waitingText", () => {
  it("says a run with nothing ahead starts in a moment", () => {
    expect(waitingText(0)).toBe("It starts in a moment.");
    expect(waitingText(null)).toBe("It starts in a moment.");
  });

  it("counts the triages ahead in words", () => {
    expect(waitingText(1)).toBe(
      "ARIA is busy: 1 triage is ahead of yours. Yours starts as soon as a place is free.",
    );
    expect(waitingText(3)).toContain("3 triages are ahead of yours");
  });
});
