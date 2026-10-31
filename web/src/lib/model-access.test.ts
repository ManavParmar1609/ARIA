import { describe, expect, it } from "vitest";

import { accessSentence, accessShort, modelAccess } from "./model-access";

describe("who answers a visitor's runs", () => {
  it("is the visitor's own key first", () => {
    const access = modelAccess("claude", ["claude", "gemini"], { left: 3, per_visitor: 5 });
    expect(access).toEqual({ kind: "own", label: "Your Claude key" });
    expect(accessSentence(access, true)).toBe(
      "Your Claude key triages your incidents and answers your questions.",
    );
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
      "Offline: triages use the rules, the calibrated model and the grounded template, and nothing leaves the server.",
    );
  });

  it("points at the key form below it on Settings, and says the short version in the sidebar", () => {
    const offline = modelAccess(null, ["gemini"], null);
    expect(accessSentence(offline, true, true)).toMatch(/Add your own key below to use a model\.$/);
    expect(accessShort(offline, true)).toBe("Offline. Add a model key");
    expect(accessShort(offline, false)).toBe("Offline: no language model");
    expect(accessShort(modelAccess("gemini", ["gemini"], null), true)).toBe(
      "Your Gemini key answers",
    );
    expect(accessShort(modelAccess(null, [], { left: 2, per_visitor: 5 }), false)).toBe(
      "The site's key answers: 2 left today",
    );
  });
});
