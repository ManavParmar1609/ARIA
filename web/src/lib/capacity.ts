import type { components } from "@/lib/api/schema";

import { shortTime } from "./format";

// The shared models' room (GET /api/v1/llm/capacity) in plain words, for Settings. ARIA keeps
// each model under its own limits: requests a minute, tokens a minute and requests a day, the
// day starting again at midnight Pacific time. Times are shown in the reader's own time zone.

export type Capacity = components["schemas"]["CapacityOut"];
export type ModelRoom = components["schemas"]["ProviderCapacityOut"];

type Clock = (iso: string) => string;

const noun = (n: number, one: string) => (n === 1 ? one : `${one}s`);

/** The models worth showing: those set up on this server, or resting after a refusal. */
export function shownModels(capacity: Capacity): ModelRoom[] {
  return capacity.providers.filter((p) => p.set_up || p.held_until);
}

/** One sentence: how many model-written triages fit today, or until when none does. */
export function capacitySummary(capacity: Capacity, time: Clock = shortTime): string {
  if (capacity.back_at) {
    return `The shared models are at their limits for now, so new triages run offline until ${time(capacity.back_at)} (your time). A key of your own is not affected.`;
  }
  const reset = `Daily counts start again at midnight Pacific time, ${time(capacity.day_resets_at)} your time.`;
  const n = capacity.runs_left_today;
  if (n == null) return `No daily limit is set for the shared models. ${reset}`;
  const more = n >= 999 ? "999 or more" : `about ${n.toLocaleString("en")}`;
  return `Room for ${more} more model-written ${noun(n, "triage")} today. ${reset}`;
}

/** "3 of 4 requests left", or "No limit". */
export function minuteWords(room: ModelRoom): string {
  const limit = room.limits?.requests_per_minute;
  if (limit == null || room.minute_requests_left == null) return "No limit";
  return `${room.minute_requests_left} of ${limit} ${noun(limit, "request")} left`;
}

/** "17 of 18 requests left, 4 held for triages in progress", or "No limit". */
export function dayWords(room: ModelRoom): string {
  const limit = room.limits?.requests_per_day;
  if (limit == null || room.day_requests_left == null) return "No limit";
  const held = room.day_requests_reserved
    ? `, ${room.day_requests_reserved} held for triages in progress`
    : "";
  return `${room.day_requests_left} of ${limit} ${noun(limit, "request")} left${held}`;
}

/** "Ready", "Not set up", or "Resting until 08:00: its daily quota is used up". */
export function stateWords(room: ModelRoom, time: Clock = shortTime): string {
  if (room.held_until) {
    const why = room.held_because ? `: ${room.held_because}` : "";
    return `Resting until ${time(room.held_until)}${why}`;
  }
  return room.set_up ? "Ready" : "Not set up";
}
