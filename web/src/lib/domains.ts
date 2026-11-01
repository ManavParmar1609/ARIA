// The new-domain tests (ring C): public, labelled data from fields ARIA was never built for, shaped
// for Test results. `make eval` writes one summary per suite under "domains" in
// docs/eval-results.json (src/aria/evals/domains.py), or, for a suite whose data was not
// downloaded, only a note saying so. Until the results hold them, `readDomains` returns null and
// the page shows nothing new. Every number comes from the results; nothing here is typed in.

/** A part of a group, as hits of a total, with its exact 95% interval. */
export interface Rate {
  hits: number;
  of: number;
  share: number;
  ci: [number, number];
}

/** A rate of misses, with its exact one-sided bound: at most `upper`, with 95% confidence. */
export interface MissRate extends Rate {
  upper: number;
}

/** How well a score ranks the cases that matter above the rest (AUROC): 0.5 is chance. */
export interface Ranking {
  auroc: number;
  ci: [number, number];
}

/** Whether the service at fault was the first suspect, or among the first three. */
export interface Naming {
  first: Rate;
  firstThree: Rate;
}

/** What a pick at random scores on average: an expectation, so it has no interval. */
export interface Chance {
  first: number;
  firstThree: number;
}

export interface AlertMethod {
  key: string;
  attackFlagged: Rate;
  attackPaged: Rate;
  routineFlagged: Rate;
  routinePaged: Rate;
}

export interface AttackStep {
  key: string;
  occurrences: number;
  flagged: number;
  paged: number;
  /** A step that means a break-in or harm, rather than looking around. */
  harmful: boolean;
}

/** Security alerts from attacked networks (AIT-ADS), cut into windows of a few minutes. */
export interface SecurityAlerts {
  key: "ait-ads";
  citation: string;
  networks: number;
  alerts: number;
  windowMin: number;
  windows: number;
  attackWindows: number;
  routineWindows: number;
  /** ARIA's probability of SEV1-2, as a score that ranks attack windows above routine ones. */
  ranking: Ranking;
  /** Every score's ranking, ARIA's included, keyed as the results key them. */
  rankings: { key: string; ranking: Ranking }[];
  perNetwork: { median: number; worst: number; belowChance: number } | null;
  /** ARIA's flags and pages first, then each other method's. */
  methods: AlertMethod[];
  /** The harmful steps that no window overlapping them paged. */
  harmfulMissed: MissRate;
  /** The same, for the detectors' own alert level. */
  detectorsMissed: MissRate | null;
  /** Each kind of attack step, as ARIA flagged and paged it. */
  steps: AttackStep[];
}

/** Faults injected one at a time (RCAEval, Nezha): the logs before each fault and after it. */
export interface FaultWindows {
  key: "rcaeval" | "nezha";
  citation: string;
  cases: number;
  windows: number;
  /** Minutes either side of a fault, where the suite cuts a fixed span. */
  windowMin: number | null;
  /** The days the faults ran on, where the data says. */
  days: number | null;
  lineCap: number;
  overCap: number;
  /** The systems the faults went into, keyed as the results key them (SS, OB, TT). */
  systems: {
    key: string;
    cases: number;
    detail: { faulty: Rate; healthy: Rate; naming: Naming } | null;
  }[];
  /** Each kind of fault, as ARIA flagged it. */
  faults: { key: string; cases: number; flagged: Rate }[];
  aria: {
    faulty: Rate;
    healthy: Rate;
    pagedFaulty: Rate;
    pagedHealthy: Rate;
    /** Cases whose window after the fault ARIA rated above, level with or below the one before. */
    paired: { higher: number; same: number; lower: number };
    ranking: Ranking;
    naming: Naming;
  };
  anyError: { faulty: Rate; healthy: Rate };
  errorRanking: Ranking;
  mostErrors: Naming;
  /** The service whose share of the logs changed most: it reads both windows; ARIA does not. */
  mostChanged: Naming | null;
  random: Chance;
}

/** Anomalies injected at four levels into two microservice systems (AnoMod). */
export interface Anomalies {
  key: "anomod";
  citation: string;
  runs: number;
  anomalous: number;
  normal: number;
  systems: { key: string; runs: number }[];
  lineCap: number;
  flagged: Rate;
  paged: Rate;
  normalFlagged: number;
  /** The level ARIA gave each system's normal run. */
  normalLevels: { system: string; level: string }[];
  anyError: { flagged: Rate; normalFlagged: number };
  naming: Naming;
  mostErrors: Naming;
  random: Chance;
  levels: { key: string; runs: number; flagged: Rate; severity: Record<string, number> }[];
}

/** Incidents on a Kubernetes cluster (ITBench-Lite): every scenario is an incident. */
export interface KubernetesIncidents {
  key: "itbench";
  citation: string;
  scenarios: number;
  /** Scenarios in the data, including any left out for want of an incident time. */
  found: number;
  windowMin: number;
  /** Scenarios with a service at fault to name. */
  withService: number;
  flagged: Rate;
  paged: Rate;
  missed: MissRate;
  naming: Naming;
  alerts: { flagged: Rate; paged: Rate };
  anyError: Rate | null;
  alertedServices: Naming;
  mostErrors: Naming;
  random: Chance;
}

export interface PriorityMethod {
  key: string;
  accuracy: number;
  accuracyCi: [number, number];
  macroF1: number;
  macroF1Ci: [number, number];
  /** Urgent tickets (levels 1-2) rated 3 or 4. */
  urgentMissed: MissRate;
  /** How many tickets the method put at each level. */
  predicted: Record<string, number>;
}

export interface Tracker {
  key: string;
  tickets: number;
  levels: Record<string, number>;
  changedAfterOpen: Rate;
  methods: PriorityMethod[];
}

/** Public Jira issues, against the priority people set (the Public Jira Dataset). */
export interface IssuePriority {
  key: "jira";
  citation: string;
  testTickets: number;
  referenceTickets: number;
  trackers: Tracker[];
  /** Every tracker's tickets together. */
  pooled: Tracker;
}

export type DomainResult =
  SecurityAlerts | FaultWindows | Anomalies | KubernetesIncidents | IssuePriority;

/** The suites, in the order the full write-up gives them. */
export const DOMAINS = ["ait-ads", "rcaeval", "anomod", "itbench", "jira", "nezha"] as const;
export type DomainKey = (typeof DOMAINS)[number];

export interface NewDomains {
  /** The suites with results, in the write-up's order. */
  results: DomainResult[];
  /** The suites not run yet: their data was not downloaded when the results were made. */
  notRun: DomainKey[];
}

// The attack steps that mean a break-in or harm, as src/aria/evals/ait_ads.py lists them.
const HARMFUL = new Set([
  "webshell",
  "cracking",
  "reverse_shell",
  "privilege_escalation",
  "service_stop",
  "dnsteal",
]);

type Json = Record<string, unknown>;

/** Thrown when a summary lacks a part it needs; `whole` turns it into null. */
class Lacking extends Error {}

function need<T>(value: T | null | undefined): T {
  if (value == null) throw new Lacking();
  return value;
}

/** What `read` builds, or null when the summary lacks a part it needs. */
function whole<T>(read: () => T): T | null {
  try {
    return read();
  } catch (error) {
    if (error instanceof Lacking) return null;
    throw error;
  }
}

const json = (x: unknown): Json | null =>
  typeof x === "object" && x !== null && !Array.isArray(x) ? (x as Json) : null;
const num = (x: unknown): number | null => (typeof x === "number" && Number.isFinite(x) ? x : null);
const str = (x: unknown): string | null => (typeof x === "string" ? x : null);
const part = (x: Json, key: string): Json => need(json(x[key]));
const figure = (x: Json, key: string): number => need(num(x[key]));

function pair(x: unknown): [number, number] | null {
  if (!Array.isArray(x) || x.length !== 2) return null;
  const [low, high] = x as unknown[];
  return typeof low === "number" && typeof high === "number" ? [low, high] : null;
}

/** A map of counts, such as tickets per level; anything that is not a number is left out. */
function counts(x: unknown): Record<string, number> {
  return Object.fromEntries(
    Object.entries(json(x) ?? {}).filter(
      (entry): entry is [string, number] => typeof entry[1] === "number",
    ),
  );
}

/** Each entry of a map that reads whole; the rest are left out. */
function each<T>(x: unknown, read: (key: string, value: unknown) => T): T[] {
  return Object.entries(json(x) ?? {}).flatMap(
    ([key, value]) => whole(() => read(key, value)) ?? [],
  );
}

function rate(x: unknown): Rate {
  const r = need(json(x));
  return {
    hits: figure(r, "hits"),
    of: figure(r, "of"),
    share: figure(r, "share"),
    ci: need(pair(r.ci95)),
  };
}

function missRate(x: unknown): MissRate {
  return { ...rate(x), upper: figure(need(json(x)), "upper95") };
}

function ranking(x: unknown): Ranking {
  const r = need(json(x));
  return { auroc: figure(r, "auroc"), ci: need(pair(r.auroc_ci95)) };
}

function naming(x: unknown): Naming {
  const r = need(json(x));
  return { first: rate(r.top1), firstThree: rate(r.top3) };
}

function chance(x: unknown): Chance {
  const r = need(json(x));
  return { first: figure(r, "top1"), firstThree: figure(r, "top3") };
}

function securityAlerts(s: Json): SecurityAlerts {
  const rankings = part(s, "ranking");
  const steps = part(s, "steps");
  const aria = part(steps, "aria");
  const per = json(s.per_scenario_auroc);
  const methods = each(s.rates, (key, value) => {
    const m = need(json(value));
    return {
      key,
      attackFlagged: rate(m.attack_flagged),
      attackPaged: rate(m.attack_paged),
      routineFlagged: rate(m.routine_flagged),
      routinePaged: rate(m.routine_paged),
    };
  });
  need(methods.find((m) => m.key === "aria"));
  return {
    key: "ait-ads",
    citation: need(str(s.citation)),
    networks: figure(s, "scenarios"),
    alerts: figure(s, "alerts"),
    windowMin: figure(s, "window_min"),
    windows: figure(s, "windows"),
    attackWindows: figure(s, "attack_windows"),
    routineWindows: figure(s, "routine_windows"),
    ranking: ranking(rankings.aria_probability),
    rankings: each(rankings, (key, value) => ({ key, ranking: ranking(value) })),
    perNetwork: per
      ? whole(() => ({
          median: figure(per, "median"),
          worst: figure(per, "worst"),
          belowChance: figure(per, "below_0_5"),
        }))
      : null,
    methods,
    harmfulMissed: missRate(aria.severe_miss),
    detectorsMissed: whole(() => missRate(part(steps, "ids_level").severe_miss)),
    steps: each(aria.by_step, (key, value) => {
      const t = need(json(value));
      return {
        key,
        occurrences: figure(t, "occurrences"),
        flagged: figure(t, "flagged"),
        paged: figure(t, "paged"),
        harmful: HARMFUL.has(key),
      };
    }),
  };
}

function faultWindows(key: FaultWindows["key"], s: Json): FaultWindows {
  const aria = part(s, "aria");
  const paged = part(aria, "paged");
  const paired = part(aria, "paired");
  const base = part(s, "baselines");
  const anyError = part(base, "any_error_line");
  const detail = json(s.by_system_detail) ?? {};
  return {
    key,
    citation: need(str(s.citation)),
    cases: figure(s, "cases"),
    windows: figure(s, "windows"),
    windowMin: num(s.window_min),
    days: Array.isArray(s.days) ? s.days.length : null,
    lineCap: figure(s, "line_cap"),
    overCap: figure(s, "windows_over_line_cap"),
    systems: Object.entries(counts(s.by_system)).map(([system, cases]) => ({
      key: system,
      cases,
      detail: whole(() => {
        const d = need(json(detail[system]));
        return {
          faulty: rate(d.faulty_flagged),
          healthy: rate(d.healthy_flagged),
          naming: naming(d.naming),
        };
      }),
    })),
    faults: each(s.by_fault, (fault, value) => {
      const f = need(json(value));
      return { key: fault, cases: figure(f, "cases"), flagged: rate(f.faulty_flagged) };
    }),
    aria: {
      faulty: rate(aria.faulty_flagged),
      healthy: rate(aria.healthy_flagged),
      pagedFaulty: rate(paged.faulty_flagged),
      pagedHealthy: rate(paged.healthy_flagged),
      paired: {
        higher: figure(paired, "higher"),
        same: figure(paired, "same"),
        lower: figure(paired, "lower"),
      },
      ranking: ranking(aria.ranking),
      naming: naming(aria.naming),
    },
    anyError: { faulty: rate(anyError.faulty_flagged), healthy: rate(anyError.healthy_flagged) },
    errorRanking: ranking(base.error_count_ranking),
    mostErrors: naming(base.naming_most_errors),
    mostChanged: whole(() => naming(base.naming_most_changed)),
    random: chance(base.naming_random_expected),
  };
}

function anomalies(s: Json): Anomalies {
  const aria = part(s, "aria");
  const base = part(s, "baselines");
  const anyError = part(base, "any_error_line");
  return {
    key: "anomod",
    citation: need(str(s.citation)),
    runs: figure(s, "runs"),
    anomalous: figure(s, "anomalous"),
    normal: figure(s, "normal"),
    systems: Object.entries(counts(s.by_system)).map(([key, runs]) => ({ key, runs })),
    lineCap: figure(s, "line_cap"),
    flagged: rate(aria.anomalous_flagged),
    paged: rate(aria.anomalous_paged),
    normalFlagged: figure(aria, "normal_flagged"),
    normalLevels: Object.entries(json(aria.normal_severity) ?? {}).flatMap(([system, level]) =>
      typeof level === "string" ? [{ system, level }] : [],
    ),
    anyError: {
      flagged: rate(anyError.anomalous_flagged),
      normalFlagged: figure(anyError, "normal_flagged"),
    },
    naming: naming(aria.naming),
    mostErrors: naming(base.naming_most_errors),
    random: chance(base.naming_random_expected),
    levels: each(s.by_level, (key, value) => {
      const l = need(json(value));
      return {
        key,
        runs: figure(l, "runs"),
        flagged: rate(l.flagged),
        severity: counts(l.severity),
      };
    }),
  };
}

function kubernetes(s: Json): KubernetesIncidents {
  const aria = part(s, "aria");
  const base = part(s, "baselines");
  const alerts = part(base, "alert_severity");
  const scenarios = figure(s, "scenarios");
  return {
    key: "itbench",
    citation: need(str(s.citation)),
    scenarios,
    found: num(s.found) ?? scenarios,
    windowMin: figure(s, "window_min"),
    withService: figure(s, "with_named_service"),
    flagged: rate(aria.flagged),
    paged: rate(aria.paged),
    missed: missRate(aria.missed),
    naming: naming(aria.naming),
    alerts: { flagged: rate(alerts.flagged), paged: rate(alerts.paged) },
    anyError: whole(() => rate(base.any_error_line)),
    alertedServices: naming(base.naming_alerted_service),
    mostErrors: naming(base.naming_most_errors),
    random: chance(base.naming_random_expected),
  };
}

function tracker(key: string, x: unknown): Tracker {
  const t = need(json(x));
  return {
    key,
    tickets: figure(t, "tickets"),
    levels: counts(t.levels),
    changedAfterOpen: rate(t.changed_after_open),
    methods: each(t.methods, (method, value) => {
      const m = need(json(value));
      return {
        key: method,
        accuracy: figure(m, "accuracy"),
        accuracyCi: need(pair(m.accuracy_ci95)),
        macroF1: figure(m, "macro_f1"),
        macroF1Ci: need(pair(m.macro_f1_ci95)),
        urgentMissed: missRate(m.urgent_missed),
        predicted: counts(m.predicted),
      };
    }),
  };
}

function issuePriority(s: Json): IssuePriority {
  const pooled = tracker("pooled", s.pooled);
  need(pooled.methods.find((m) => m.key === "aria"));
  return {
    key: "jira",
    citation: need(str(s.citation)),
    testTickets: figure(s, "test_tickets"),
    referenceTickets: figure(s, "reference_tickets"),
    trackers: each(s.instances, tracker),
    pooled,
  };
}

const READERS: Record<DomainKey, (summary: Json) => DomainResult> = {
  "ait-ads": securityAlerts,
  rcaeval: (summary) => faultWindows("rcaeval", summary),
  anomod: anomalies,
  itbench: kubernetes,
  jira: issuePriority,
  nezha: (summary) => faultWindows("nezha", summary),
};

/**
 * The results' "domains" object, shaped for the page: null when the results have none. A suite
 * whose summary lacks a part the page needs is left out, rather than shown half-read.
 */
export function readDomains(domains: unknown): NewDomains | null {
  const all = json(domains);
  if (!all) return null;
  const results: DomainResult[] = [];
  const notRun: DomainKey[] = [];
  for (const key of DOMAINS) {
    const summary = json(all[key]);
    if (!summary) continue;
    if ("missing" in summary) {
      notRun.push(key);
      continue;
    }
    const result = whole(() => READERS[key](summary));
    if (result) results.push(result);
  }
  return results.length || notRun.length ? { results, notRun } : null;
}
