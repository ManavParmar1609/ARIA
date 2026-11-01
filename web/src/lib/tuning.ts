// What each test's results were used for while ARIA was being changed, so a reader knows which
// numbers are clean tests. The record is config/eval_registry.yaml, which `make eval` copies into
// the results as "registry"; until it has, `readTuning` returns null and the page shows no badges.

/** Cleanest first: nobody looked; looked at, though nothing was chosen by it; a change was. */
export const STATUSES = ["untouched", "seen", "tuned"] as const;
export type TuningStatus = (typeof STATUSES)[number];

export interface TuningEntry {
  /** The suite's key in the results, such as "real.bgl" or "domains.jira". */
  suite: string;
  /** "A": familiar systems; "B": systems held out in turn; "C": real data. */
  ring: string;
  status: TuningStatus;
  /** The ISO date the record gives: looked at, or tuned, since then. */
  since: string | null;
  note: string;
}

export type TuningRecord = Record<string, TuningEntry>;

/** What a badge shows, and the note its card opens. */
export interface Tuning {
  status: TuningStatus;
  since: string | null;
  note: string;
}

const json = (x: unknown): Record<string, unknown> | null =>
  typeof x === "object" && x !== null && !Array.isArray(x) ? (x as Record<string, unknown>) : null;

/** The results' "registry" object, by suite: null when the results have none. */
export function readTuning(registry: unknown): TuningRecord | null {
  const suites = json(json(registry)?.suites);
  if (!suites) return null;
  const record: TuningRecord = {};
  for (const [suite, raw] of Object.entries(suites)) {
    const entry = json(raw);
    const status = STATUSES.find((s) => s === entry?.status);
    if (!entry || !status) continue;
    const since = typeof entry.since === "string" ? /^\d{4}-\d{2}-\d{2}/.exec(entry.since) : null;
    record[suite] = {
      suite,
      ring: typeof entry.ring === "string" ? entry.ring : "",
      status,
      since: since?.[0] ?? null,
      note: typeof entry.note === "string" ? entry.note.trim() : "",
    };
  }
  return Object.keys(record).length ? record : null;
}

const WORD: Record<TuningStatus, string> = {
  untouched: "Untouched",
  seen: "Looked at",
  tuned: "Tuned",
};

/** What a badge says: "Untouched", "Looked at", or "Tuned since 2026-11-01". */
export function tuningLabel({ status, since }: Pick<Tuning, "status" | "since">): string {
  return status === "tuned" && since ? `${WORD.tuned} since ${since}` : WORD[status];
}

/** The title of the card a badge opens: its status, with the record's date whatever the status. */
export function tuningTitle({ status, since }: Pick<Tuning, "status" | "since">): string {
  return since ? `${WORD[status]} since ${since}` : WORD[status];
}

const PAST: Record<TuningStatus, string> = {
  untouched: "left untouched",
  seen: "looked at",
  tuned: "tuned",
};
const list = (items: string[]) =>
  new Intl.ListFormat("en-GB", { type: "conjunction" }).format(items);
const was = (n: number) => (n === 1 ? "was" : "were");

/**
 * The badge for a group of tests, such as every test on real data: no cleaner than its least clean
 * test. A group of one says what that test's record says; a larger group counts its tests by
 * status and names the least clean ones, by the names in `names` where it has them.
 */
export function ringTuning(
  record: TuningRecord,
  ring: string,
  names: Record<string, string> = {},
): Tuning | null {
  const entries = Object.values(record).filter((e) => e.ring === ring);
  const [first] = entries;
  if (!first) return null;
  if (entries.length === 1) return { status: first.status, since: first.since, note: first.note };
  const worst = STATUSES.findLast((s) => entries.some((e) => e.status === s)) ?? first.status;
  const least = entries.filter((e) => e.status === worst);
  const since = least.flatMap((e) => (e.since ? [e.since] : [])).sort()[0] ?? null;
  const tally = STATUSES.flatMap((s) => {
    const n = entries.filter((e) => e.status === s).length;
    return n ? [`${n} ${was(n)} ${PAST[s]}`] : [];
  });
  const counted =
    least.length === entries.length
      ? `All ${entries.length} tests in this group ${was(entries.length)} ${PAST[worst]}.`
      : `Of the ${entries.length} tests in this group, ${list(tally)}.`;
  const named =
    least.length === entries.length || worst === "untouched"
      ? ""
      : ` ${WORD[worst]}: ${list(
          least.map((e) => `${names[e.suite] ?? e.suite}${e.since ? ` (since ${e.since})` : ""}`),
        )}.`;
  return {
    status: worst,
    since,
    note: `The badge shows the least clean test in this group. ${counted}${named}`,
  };
}
