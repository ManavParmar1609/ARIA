import type { Severity, SeverityAssessment } from "@/lib/api/types";

// Severity in words a newcomer can act on: each level's name, the same one the report's first line
// uses, and what teams usually do about it (item 16).

export const LEVEL_WORD: Record<Severity, string> = {
  SEV1: "critical",
  SEV2: "high",
  SEV3: "moderate",
  SEV4: "low",
};

export const LEVEL_RESPONSE: Record<Severity, string> = {
  SEV1: "Widespread outage or data at risk. Usual response: page everyone needed, now.",
  SEV2: "Major degradation or a failing critical part. Usual response: page the on-call team.",
  SEV3: "Contained errors with limited user impact. Usual response: fix it during working hours.",
  SEV4: "Informational, or noise. Usual response: no action needed now.",
};

/** "SEV1, SEV2 or SEV3". */
export function orList(levels: readonly string[]): string {
  if (levels.length <= 1) return levels[0] ?? "";
  return `${levels.slice(0, -1).join(", ")} or ${levels.at(-1)}`;
}

/**
 * The short list of likely levels, in words, and the one ARIA plans for. When ARIA asked a person
 * to check the level, the sentence says so while the run waits, the same way the report and the
 * review do, and afterwards says what came of it.
 */
export function shortListText(
  a: Pick<
    SeverityAssessment,
    "severity" | "prediction_set" | "set_empty" | "decided_by" | "needs_review"
  >,
  status?: string,
): string {
  const set = a.prediction_set;
  const unsure = a.needs_review || a.decided_by === "fallback";
  const approved = status === "published";
  const ended = approved || status === "rejected";
  const plans = ended ? "planned" : "plans";
  // A check while the run waits; what came of it once a person decided.
  const ask = (verb: "confirm" | "decide") =>
    !unsure ? "" : !ended ? ` Please ${verb}.` : approved ? " A reviewer confirmed it." : "";
  if (a.decided_by === "human") return `A reviewer set ${a.severity}.`;
  if (a.set_empty || set.length === 0) {
    return `No level was likely enough on its own. ARIA ${plans} for ${a.severity}, the most likely.${ask("decide")}`;
  }
  if (set.length === 1) {
    if (set[0] !== a.severity) {
      return `${set[0]} is likely, but a safety rule keeps it at ${a.severity}.`;
    }
    if (!unsure) return `Only ${a.severity} is likely.`;
    return ended
      ? `Probably ${a.severity}. ARIA wasn't sure enough to decide alone.${ask("confirm")}`
      : `Probably ${a.severity}. ARIA isn't sure enough to decide alone, so please confirm.`;
  }
  const chose =
    a.decided_by === "llm"
      ? `A language model chose ${a.severity}.`
      : `ARIA ${plans} for ${a.severity}.`;
  return `Could be ${orList(set)}. ${chose}${ask("confirm")}`;
}
