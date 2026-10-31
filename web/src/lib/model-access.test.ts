import { describe, expect, it } from "vitest";

import { accessSentence, modelAccess } from "./model-access";

describe("who answers a visitor's runs", () => {
  it("is the visitor's own key first", () => {
    const access = modelAccess("claude", ["claude", "gemini"], { left: 3, per_visitor: 5 });
    expect(access).toEqual({ kind: "own", label: "Your Claude key" });
    expect(accessSentence(access, true)).toBe("Your Claude key answers your runs and questions.");
  });

  it("is the site's key while today's share lasts, and says how much is left", () => {
    const access = modelAccess(null, ["gemini"], { left: 3, per_visitor: 5, per_day: 100 });
    expect(access.label).toBe("The site's key (shared, limited)");
    expect(accessSentence(access, true)).toContain("3 left today");
    expect(modelAccess(null, [], { left: null }).label).toBe("The site's key");
  });

  it("goes offline once the share is used, and says how to bring a key", () => {
    const used = modelAccess(null, ["gemini"], { left: 0, per_visitor: 5 });
    expect(used).toEqual({ kind: "offline", label: "Offline", usedUp: true });
    expect(accessSentence(used, true)).toMatch(/^Offline for today: .* Add your own key/);
    const none = modelAccess("openai", ["gemini"], null);
    expect(none.kind).toBe("offline");
    expect(accessSentence(none, false)).toBe(
      "Offline: runs use the rules, the calibrated model and the grounded template, and nothing leaves the server.",
    );
  });
});
