// The incident library's filters, order and summaries, as pure functions of the incidents: the
// page (components/console/memory.tsx) and its charts (library-charts.tsx) only draw them.
//
// Every figure here is computed from the whole library the API returned, never typed in, and every
// title states what the figures show in plain words.

import { SEVERITIES, isSeverity, type IncidentOut, type Severity } from "@/lib/api/types";
import { failureName } from "@/lib/failure-modes";
import { capitalise, listed, plural, stripSeverity } from "@/lib/format";
import { LEVEL_WORD, orList } from "@/lib/levels";
import { systemName } from "@/lib/systems";

// --- one entry per incident ---------------------------------------------------------------------

/** One incident in the library and when each of its sightings was last seen. */
export interface LibraryEntry {
  incident: IncidentOut;
  /** One per entry the library holds for it (several when it was seen again). */
  seen: { when: string | null; times: number }[];
}

/**
 * Entries that tell the same story (system, title, fix and source) as one, counting all their
 * sightings: the seeded library holds the same sample incident more than once. The first entry,
 * which is the closest one in a search, speaks for them all.
 */
export function mergeEntries(incidents: IncidentOut[]): LibraryEntry[] {
  const byStory = new Map<string, LibraryEntry>();
  for (const incident of incidents) {
    const key = [
      incident.system,
      stripSeverity(incident.title),
      incident.resolution,
      incident.source,
    ].join("\u0000");
    const times = Math.max(1, incident.occurrences);
    const sighting = { when: incident.last_seen ?? null, times };
    const first = byStory.get(key);
    if (!first) {
      byStory.set(key, { incident, seen: [sighting] });
      continue;
    }
    const lasts = [first.incident.last_seen, incident.last_seen].filter(
      (when): when is string => !!when,
    );
    byStory.set(key, {
      incident: {
        ...first.incident,
        occurrences: Math.max(1, first.incident.occurrences) + times,
        last_seen: lasts.sort().at(-1) ?? null,
      },
      seen: [...first.seen, sighting],
    });
  }
  return [...byStory.values()];
}

// --- where an incident came from ----------------------------------------------------------------

/** Where an entry came from, from its source and whether it was built from a sample. */
export function originOf(incident: Pick<IncidentOut, "source" | "synthetic">): string {
  if (incident.source === "curated") return "sample";
  if (incident.source === "run") return incident.synthetic ? "approved-sample" : "approved";
  return incident.source;
}

const ORIGIN_NAMES: Record<string, string> = {
  sample: "Built from a sample",
  approved: "Approved triage of real logs",
  "approved-sample": "Approved triage of a sample",
  memory: "Added another way",
};

export const originName = (key: string): string => ORIGIN_NAMES[key] ?? `From ${key}`;

// --- filters ------------------------------------------------------------------------------------

export interface Filters {
  severity: Severity[];
  system: string[];
  kind: string[];
  origin: string[];
  runbook: boolean;
}

export type Dimension = keyof Filters;
export type ListDimension = Exclude<Dimension, "runbook">;

export const NO_FILTERS: Filters = {
  severity: [],
  system: [],
  kind: [],
  origin: [],
  runbook: false,
};

/** Each filter's name in the address: `?sev=SEV1&sev=SEV2&system=hdfs&kind=…&from=…&runbook=1`. */
export const PARAMS: Record<Dimension, string> = {
  severity: "sev",
  system: "system",
  kind: "kind",
  origin: "from",
  runbook: "runbook",
};

/** Each filter's label on the page, which advice quotes so it names the control people see. */
export const FILTER_LABELS: Record<Dimension, string> = {
  severity: "Severity",
  system: "System",
  kind: "Kind of failure",
  origin: "Where it came from",
  runbook: "Has a runbook",
};

type Params = Pick<URLSearchParams, "get" | "getAll">;

/** The filters in an address. Values may repeat (`sev=SEV1&sev=SEV2`) or be comma-separated. */
export function readFilters(params: Params): Filters {
  const list = (key: string) => [
    ...new Set(
      params
        .getAll(key)
        .flatMap((value) => value.split(","))
        .map((value) => value.trim())
        .filter(Boolean),
    ),
  ];
  const levels = list(PARAMS.severity).map((value) => value.toUpperCase());
  return {
    severity: SEVERITIES.filter((level) => levels.includes(level)),
    system: list(PARAMS.system).sort(),
    kind: list(PARAMS.kind).sort(),
    origin: list(PARAMS.origin).sort(),
    runbook: ["1", "yes", "true"].includes(params.get(PARAMS.runbook) ?? ""),
  };
}

/** The address's query with these filters in place of the ones it had; other parameters stay. */
export function withFilters(params: URLSearchParams | string, filters: Filters): string {
  const next = new URLSearchParams(params.toString());
  for (const key of Object.values(PARAMS)) next.delete(key);
  for (const level of filters.severity) next.append(PARAMS.severity, level);
  for (const system of filters.system) next.append(PARAMS.system, system);
  for (const kind of filters.kind) next.append(PARAMS.kind, kind);
  for (const origin of filters.origin) next.append(PARAMS.origin, origin);
  if (filters.runbook) next.set(PARAMS.runbook, "1");
  return next.toString();
}

/** The filters with one value of a list filter switched on or off. */
export function toggled(filters: Filters, dimension: ListDimension, value: string): Filters {
  const current: string[] = filters[dimension];
  const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value];
  if (dimension === "severity") {
    return { ...filters, severity: SEVERITIES.filter((level) => next.includes(level)) };
  }
  return { ...filters, [dimension]: next.sort() };
}

export function cleared(filters: Filters, dimension: Dimension): Filters {
  return { ...filters, [dimension]: NO_FILTERS[dimension] };
}

/** The filters that are on, in the order the page shows them. */
export function activeDimensions(filters: Filters): Dimension[] {
  return (Object.keys(PARAMS) as Dimension[]).filter((dimension) =>
    dimension === "runbook" ? filters.runbook : filters[dimension].length > 0,
  );
}

export function valueOf(incident: IncidentOut, dimension: ListDimension): string {
  switch (dimension) {
    case "severity":
      return incident.severity;
    case "system":
      return incident.system;
    case "kind":
      return incident.failure_mode;
    case "origin":
      return originOf(incident);
  }
}

/** Whether an incident passes every filter, or every filter but one (`except`). */
export function matches(incident: IncidentOut, filters: Filters, except?: Dimension): boolean {
  for (const dimension of ["severity", "system", "kind", "origin"] as const) {
    const chosen: string[] = filters[dimension];
    if (dimension !== except && chosen.length && !chosen.includes(valueOf(incident, dimension))) {
      return false;
    }
  }
  return except === "runbook" || !filters.runbook || !!incident.runbook_slug;
}

/**
 * How many incidents each value of a filter would show: counted with every other filter applied
 * but not this one, so each option says how many incidents it holds.
 */
export function facet(
  incidents: IncidentOut[],
  filters: Filters,
  dimension: ListDimension,
): Map<string, number> {
  const counts = new Map<string, number>();
  for (const incident of incidents) {
    if (!matches(incident, filters, dimension)) continue;
    const value = valueOf(incident, dimension);
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  return counts;
}

export interface FilterOption {
  value: string;
  name: string;
  count: number;
  chosen: boolean;
}

/** A filter's options: every value the library holds (and any chosen one), with its count. */
export function filterOptions(
  library: IncidentOut[],
  filters: Filters,
  dimension: ListDimension,
): FilterOption[] {
  const counts = facet(library, filters, dimension);
  const chosen: string[] = filters[dimension];
  const values = new Set([...library.map((i) => valueOf(i, dimension)), ...chosen]);
  const options = [...values].map((value) => ({
    value,
    name: nameOf(dimension, value),
    count: counts.get(value) ?? 0,
    chosen: chosen.includes(value),
  }));
  if (dimension === "severity") {
    return SEVERITIES.map(
      (level) =>
        options.find((option) => option.value === level) ?? {
          value: level,
          name: nameOf("severity", level),
          count: 0,
          chosen: false,
        },
    );
  }
  return options.sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}

/** A name as a label, its first letter in capitals, unless it starts with a code name such as
 * "mod_jk", which keeps its own spelling. */
export function asLabel(name: string): string {
  return /^[a-z0-9]+_/.test(name) ? name : capitalise(name);
}

export function nameOf(dimension: ListDimension, value: string): string {
  switch (dimension) {
    case "severity":
      return isSeverity(value) ? `${value} ${LEVEL_WORD[value]}` : value;
    case "system":
      return systemName(value);
    case "kind":
      return failureName(value);
    case "origin":
      return originName(value);
  }
}

/** How many incidents would show with each filter that is on cleared, the most first. */
export function loosenings(
  incidents: IncidentOut[],
  filters: Filters,
): { dimension: Dimension; count: number }[] {
  return activeDimensions(filters)
    .map((dimension) => ({
      dimension,
      count: incidents.filter((incident) => matches(incident, filters, dimension)).length,
    }))
    .sort((a, b) => b.count - a.count);
}

/** "Loosen “Severity”: 12 incidents match without it." Null when no single filter is to blame. */
export function loosenAdvice(incidents: IncidentOut[], filters: Filters): string | null {
  const best = loosenings(incidents, filters)[0];
  if (!best || best.count === 0) return null;
  return `Loosen “${FILTER_LABELS[best.dimension]}”: ${plural(best.count, "incident")} ${
    best.count === 1 ? "matches" : "match"
  } without it.`;
}

// --- order --------------------------------------------------------------------------------------

export type SortKey = "recent" | "seen" | "serious" | "closest";

export const SORT_NAMES: Record<SortKey, string> = {
  recent: "Most recent",
  seen: "Most seen",
  serious: "Most serious",
  closest: "Closest match",
};

/** The order in the address, if it names one this list can take. */
export function readSort(params: Params, searching: boolean): SortKey {
  const sort = params.get("sort");
  if (sort === "seen" || sort === "serious" || sort === "recent") return sort;
  if (sort === "closest" && searching) return sort;
  return searching ? "closest" : "recent";
}

const RANK: Record<string, number> = { SEV1: 0, SEV2: 1, SEV3: 2, SEV4: 3 };
const time = (iso: string | null | undefined) => (iso ? Date.parse(iso) : Number.NaN);

function byRecent(a: IncidentOut, b: IncidentOut): number {
  const [x, y] = [time(a.last_seen), time(b.last_seen)];
  if (Number.isNaN(x) || Number.isNaN(y)) return Number.isNaN(x) ? (Number.isNaN(y) ? 0 : 1) : -1;
  return y - x;
}

const bySeen = (a: IncidentOut, b: IncidentOut) => b.occurrences - a.occurrences;
const bySerious = (a: IncidentOut, b: IncidentOut) =>
  (RANK[a.severity] ?? 9) - (RANK[b.severity] ?? 9);

/** The entries in this order; "closest" keeps the search's order. */
export function sortEntries<T extends { incident: IncidentOut }>(entries: T[], sort: SortKey): T[] {
  const order =
    sort === "seen"
      ? [bySeen, byRecent]
      : sort === "serious"
        ? [bySerious, bySeen, byRecent]
        : sort === "recent"
          ? [byRecent, bySeen]
          : [];
  if (order.length === 0) return entries;
  return [...entries].sort((a, b) => {
    for (const compare of order) {
      const difference = compare(a.incident, b.incident);
      if (difference) return difference;
    }
    return 0;
  });
}

// --- the summary --------------------------------------------------------------------------------

export interface Summary {
  incidents: number;
  sightings: number;
  systems: number;
  /** The share with a runbook to follow, 0 to 1. */
  withRunbook: number;
}

export function summarise(entries: LibraryEntry[]): Summary {
  const incidents = entries.map((entry) => entry.incident);
  return {
    incidents: incidents.length,
    sightings: incidents.reduce((sum, incident) => sum + Math.max(1, incident.occurrences), 0),
    systems: new Set(incidents.map((incident) => incident.system)).size,
    withRunbook: incidents.length
      ? incidents.filter((incident) => incident.runbook_slug).length / incidents.length
      : 0,
  };
}

/** A share as a whole percentage that never rounds a part to nothing or to everything. */
export function percent(share: number): string {
  if (share <= 0) return "0%";
  if (share >= 1) return "100%";
  return `${Math.min(99, Math.max(1, Math.round(share * 100)))}%`;
}

// --- bars ---------------------------------------------------------------------------------------

export interface Bar {
  /** The filter value it stands for; empty for "Other". */
  value: string;
  name: string;
  count: number;
  share: number;
  chosen: boolean;
  /** For "Other": the values folded into it, the most first. */
  members?: { value: string; name: string; count: number }[];
}

export interface BarSet {
  bars: Bar[];
  /** Every incident the bars count (the incidents that pass the other filters). */
  total: number;
  /** The values chosen in this filter. */
  chosen: string[];
}

/** One bar per severity level, most serious first, counted with the other filters applied. */
export function severityBars(entries: LibraryEntry[], filters: Filters): BarSet {
  const incidents = entries.map((entry) => entry.incident);
  const counts = facet(incidents, filters, "severity");
  const total = [...counts.values()].reduce((sum, count) => sum + count, 0);
  return {
    bars: SEVERITIES.map((level) => {
      const count = counts.get(level) ?? 0;
      return {
        value: level,
        name: `${level} ${LEVEL_WORD[level]}`,
        count,
        share: total ? count / total : 0,
        chosen: filters.severity.includes(level),
      };
    }),
    total,
    chosen: filters.severity,
  };
}

/**
 * The values of a filter with the most incidents, each a bar, then the rest as one "Other" bar.
 * A chosen value always keeps its own bar, so pressing it again is always possible.
 */
export function topBars(
  entries: LibraryEntry[],
  filters: Filters,
  dimension: "system" | "kind",
  limit = 6,
): BarSet {
  const incidents = entries.map((entry) => entry.incident);
  const counts = facet(incidents, filters, dimension);
  const chosen = filters[dimension];
  const total = [...counts.values()].reduce((sum, count) => sum + count, 0);
  const all = [...counts.entries()]
    .map(([value, count]) => ({ value, name: nameOf(dimension, value), count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  for (const value of chosen) {
    if (!counts.has(value)) all.push({ value, name: nameOf(dimension, value), count: 0 });
  }
  let shown = all.filter((bar, index) => index < limit || chosen.includes(bar.value));
  let rest = all.filter((bar) => !shown.includes(bar));
  // A lone leftover is shown by name rather than as "1 other".
  if (rest.length === 1) [shown, rest] = [all, []];
  const bar = (b: { value: string; name: string; count: number }): Bar => ({
    ...b,
    share: total ? b.count / total : 0,
    chosen: chosen.includes(b.value),
  });
  const bars = shown.map(bar);
  if (rest.length > 0) {
    const count = rest.reduce((sum, b) => sum + b.count, 0);
    bars.push({
      value: "",
      name: dimension === "system" ? `${rest.length} other systems` : `${rest.length} other kinds`,
      count,
      share: total ? count / total : 0,
      chosen: false,
      members: rest,
    });
  }
  return { bars, total, chosen };
}

/** The incidents seen more than once, the most seen first, then the most recent. */
export function mostSeen(entries: LibraryEntry[]): LibraryEntry[] {
  return sortEntries(
    entries.filter((entry) => entry.incident.occurrences > 1),
    "seen",
  );
}

/** How many share first place among the most seen. */
export const tiedFirst = (repeats: LibraryEntry[]) =>
  repeats.filter((entry) => entry.incident.occurrences === repeats[0]?.incident.occurrences).length;

/** The most seen to chart: five, or the whole tie for first place when it is only a few more. */
export function mostSeenTop(repeats: LibraryEntry[], few = 5, most = 8): LibraryEntry[] {
  const tied = tiedFirst(repeats);
  return repeats.slice(0, tied > few && tied <= most ? tied : few);
}

// --- over time ----------------------------------------------------------------------------------

export type Unit = "day" | "week" | "month";

export interface Timeline {
  unit: Unit;
  /** Every day, week or month from the first sighting to the last, empty ones included. */
  buckets: { start: string; count: number }[];
  total: number;
}

const DAY = 86_400_000;
const dayOf = (iso: string) => Math.floor(Date.parse(iso) / DAY) * DAY;

function bucketStart(ms: number, unit: Unit): number {
  const date = new Date(ms);
  if (unit === "day") return ms;
  if (unit === "week") return ms - ((date.getUTCDay() + 6) % 7) * DAY; // Mondays
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1);
}

function nextBucket(ms: number, unit: Unit): number {
  if (unit === "day") return ms + DAY;
  if (unit === "week") return ms + 7 * DAY;
  const date = new Date(ms);
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 1);
}

/** Days with a sighting before the shape over time is worth a chart. */
export const TIMELINE_MIN_DAYS = 5;

/**
 * Sightings by when they were last seen, by day, week or month to suit the span. Null when they
 * fall on too few days to show a shape.
 */
export function timeline(entries: LibraryEntry[]): Timeline | null {
  const seen = entries
    .flatMap((entry) => entry.seen)
    .filter((s): s is { when: string; times: number } => !!s.when && !Number.isNaN(time(s.when)));
  const days = new Set(seen.map((s) => dayOf(s.when)));
  if (days.size < TIMELINE_MIN_DAYS) return null;
  const first = Math.min(...days);
  const last = Math.max(...days);
  const span = (last - first) / DAY;
  const unit: Unit = span <= 45 ? "day" : span <= 280 ? "week" : "month";
  const counts = new Map<number, number>();
  for (const s of seen) {
    const start = bucketStart(dayOf(s.when), unit);
    counts.set(start, (counts.get(start) ?? 0) + s.times);
  }
  const buckets: Timeline["buckets"] = [];
  for (let at = bucketStart(first, unit); at <= last; at = nextBucket(at, unit)) {
    buckets.push({ start: new Date(at).toISOString().slice(0, 10), count: counts.get(at) ?? 0 });
  }
  if (buckets.length < 4) return null;
  return { unit, buckets, total: seen.reduce((sum, s) => sum + s.times, 0) };
}

/** "24 May", "the week of 18 May" or "May 2026"; the year joins a day when the span crosses one. */
export function bucketName(start: string, unit: Unit, withYear = false): string {
  const date = new Date(`${start}T00:00:00Z`);
  if (unit === "month") {
    return date.toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });
  }
  const day = date.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    ...(withYear ? { year: "numeric" } : {}),
    timeZone: "UTC",
  });
  return unit === "week" ? `the week of ${day}` : day;
}

// --- titles: each chart's takeaway, in words ----------------------------------------------------

const are = (count: number) => (count === 1 ? "is" : "are");
const leaders = (bars: Bar[]) => {
  const named = bars.filter((bar) => bar.value);
  const most = Math.max(0, ...named.map((bar) => bar.count));
  return most > 0 ? named.filter((bar) => bar.count === most) : [];
};
const chosenCount = (set: BarSet) =>
  set.bars.filter((bar) => bar.chosen).reduce((sum, bar) => sum + bar.count, 0);
const ofTotal = (count: number, total: number) =>
  `${count.toLocaleString("en")} of the ${plural(total, "incident")} here`;

export function severityTitle(set: BarSet): string {
  if (set.chosen.length) {
    const count = chosenCount(set);
    return `${ofTotal(count, set.total)} ${are(count)} ${orList(set.chosen)}`;
  }
  const top = leaders(set.bars);
  const [lead] = top;
  if (!lead) return "No incident here has a level";
  if (top.length > 1) return `${listed(top.map((bar) => bar.value))} are the most common levels`;
  if (lead.count === set.total) {
    return set.total === 1
      ? `The one incident here is ${lead.value}`
      : `Every incident here is ${lead.value}`;
  }
  return lead.share > 0.5
    ? `Most incidents here are ${lead.value}`
    : `${lead.value} is the most common level`;
}

export function systemTitle(set: BarSet): string {
  if (set.chosen.length) {
    const count = chosenCount(set);
    const names =
      set.chosen.length > 3
        ? `the ${set.chosen.length} systems you chose`
        : orList(set.chosen.map(systemName));
    return `${ofTotal(count, set.total)} ${count === 1 ? "comes" : "come"} from ${names}`;
  }
  const top = leaders(set.bars);
  const [lead] = top;
  if (!lead) return "No incident here names its system";
  if (top.length > 2) return `${top.length} systems tie for the most incidents`;
  if (top.length === 2) return `${listed(top.map((bar) => bar.name))} have the most incidents`;
  if (lead.count === set.total) return `Every incident here comes from ${lead.name}`;
  return lead.share > 0.5
    ? `Most incidents here come from ${lead.name}`
    : `${lead.name} has the most incidents`;
}

export function kindTitle(set: BarSet): string {
  if (set.chosen.length) {
    const count = chosenCount(set);
    const names =
      set.chosen.length > 3
        ? `one of the ${set.chosen.length} kinds you chose`
        : orList(set.chosen.map(failureName));
    return `${ofTotal(count, set.total)} ${count === 1 ? "shows" : "show"} ${names}`;
  }
  const top = leaders(set.bars);
  const [lead] = top;
  if (!lead) return "No incident here names its kind of failure";
  if (top.length > 2) {
    return `${top.length} kinds of failure tie for the most, with ${plural(lead.count, "incident")} each`;
  }
  if (top.length === 2) {
    return `The most common kinds of failure are ${listed(top.map((bar) => bar.name))}`;
  }
  if (lead.count === set.total) return `Every incident here shows ${lead.name}`;
  return lead.share > 0.5
    ? `Most incidents here show ${lead.name}`
    : `The most common kind of failure is ${lead.name}`;
}

export function mostSeenTitle(top: LibraryEntry[]): string {
  const most = top[0]?.incident.occurrences ?? 0;
  const tied = top.filter((entry) => entry.incident.occurrences === most);
  const [lead] = tied;
  if (!lead) return "No incident here was seen more than once";
  if (tied.length > 1) {
    return `${tied.length} incidents were seen most often, ${most} times each`;
  }
  return `Seen most often, ${most} times: ${stripSeverity(lead.incident.title)}`;
}

export function timelineTitle(line: Timeline): string {
  const most = Math.max(...line.buckets.map((bucket) => bucket.count));
  const peaks = line.buckets.filter((bucket) => bucket.count === most);
  const years = new Set(line.buckets.map((bucket) => bucket.start.slice(0, 4))).size > 1;
  const on = line.unit === "day" ? "on " : line.unit === "week" ? "in " : "in ";
  if (peaks.length > 2) return `No single ${line.unit} stands out`;
  const when = listed(peaks.map((bucket) => bucketName(bucket.start, line.unit, years)));
  return peaks.length === 1 && most / line.total > 0.5
    ? `Most sightings came ${on}${when}`
    : `Sightings peaked ${on}${when}`;
}
