import { describe, expect, it } from "vitest";

import {
  capacitySummary,
  dayWords,
  minuteWords,
  shownModels,
  stateWords,
  type Capacity,
  type ModelRoom,
} from "./capacity";

// A clock that names the moment it was given, so the words do not depend on the test's zone.
const at = (iso: string) => `[${iso.slice(11, 16)}]`;

function room(over: Partial<ModelRoom> = {}): ModelRoom {
  return {
    name: "gemini",
    model: "gemini-3.6-flash",
    set_up: true,
    limits: { requests_per_minute: 4, tokens_per_minute: 90_000, requests_per_day: 18 },
    minute_requests_left: 3,
    minute_tokens_left: 89_000,
    day_requests_left: 17,
    day_requests_used: 1,
    day_requests_reserved: 0,
    minute_resets_at: null,
    held_until: null,
    held_because: null,
    ...over,
  };
}

function capacity(over: Partial<Capacity> = {}): Capacity {
  return {
    timezone: "America/Los_Angeles",
    margin: 0.1,
    day_resets_at: "2026-11-02T08:00:00Z",
    runs_left_today: 12,
    back_at: null,
    providers: [room()],
    ...over,
  };
}

describe("the shared models' room in words", () => {
  it("says how many model-written triages still fit, and when the day starts again", () => {
    expect(capacitySummary(capacity(), at)).toBe(
      "Room for about 12 more model-written triages today. Daily counts start again at midnight Pacific time, [08:00] your time.",
    );
    expect(capacitySummary(capacity({ runs_left_today: 1 }), at)).toContain(
      "1 more model-written triage today",
    );
    expect(capacitySummary(capacity({ runs_left_today: 999 }), at)).toContain("999 or more");
    expect(capacitySummary(capacity({ runs_left_today: null }), at)).toMatch(/^No daily limit/);
  });

  it("says until when triages run offline while the models are at their limits", () => {
    const full = capacity({ runs_left_today: 0, back_at: "2026-11-02T08:00:00Z" });
    expect(capacitySummary(full, at)).toBe(
      "The shared models are at their limits for now, so new triages run offline until [08:00] (your time). A key of your own is not affected.",
    );
  });

  it("reads each model's minute, day and state", () => {
    expect(minuteWords(room())).toBe("3 of 4 requests left");
    expect(dayWords(room())).toBe("17 of 18 requests left");
    expect(dayWords(room({ day_requests_reserved: 4, day_requests_left: 13 }))).toBe(
      "13 of 18 requests left, 4 held for triages in progress",
    );
    const unlimited = room({ limits: null, minute_requests_left: null, day_requests_left: null });
    expect([minuteWords(unlimited), dayWords(unlimited)]).toEqual(["No limit", "No limit"]);
    expect(stateWords(room(), at)).toBe("Ready");
    expect(stateWords(room({ set_up: false }), at)).toBe("Not set up");
    const resting = room({
      held_until: "2026-11-02T08:00:00Z",
      held_because: "its daily quota is used up",
    });
    expect(stateWords(resting, at)).toBe("Resting until [08:00]: its daily quota is used up");
  });

  it("shows the models set up here, and any resting after a refusal", () => {
    const providers = [
      room({ name: "gemini" }),
      room({ name: "gemma", set_up: false }),
      room({ name: "claude", set_up: false, held_until: "2026-11-02T08:00:00Z" }),
    ];
    expect(shownModels(capacity({ providers })).map((p) => p.name)).toEqual(["gemini", "claude"]);
  });
});
