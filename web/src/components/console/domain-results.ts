import { inTen } from "@/components/console/test-questions";
import type {
  Anomalies,
  DomainKey,
  DomainResult,
  FaultWindows,
  IssuePriority,
  KubernetesIncidents,
  MissRate,
  PriorityMethod,
  Ranking,
  Rate,
  SecurityAlerts,
  Tracker,
} from "@/lib/domains";
import { count as words } from "@/lib/format";

// What each new-domain test means for the person on call: a verdict in plain words, the numbers
// beside the strongest simple methods, and where ARIA falls short. As with the other results on
// Test results, every word that compares or judges is chosen from the numbers, so a rerun of
// `make eval` can never leave a sentence saying the opposite of its numbers. A verdict is one
// sentence that gives shares in tenths ("about 3 in 10"); the exact figures follow it.

/** How a card presents its suite, and the heading of its section in docs/evaluation.md. */
export interface DomainCard {
  id: string;
  title: string;
  /** The card's name in the page's contents. */
  label: string;
  /** The suite's section heading in the full write-up (src/aria/evals/report_domains.py). */
  heading: string;
}

export const DOMAIN_CARDS: Record<DomainKey, DomainCard> = {
  "ait-ads": {
    id: "ev-ait-ads",
    title: "Security alerts from attacked networks",
    label: "Security alerts",
    heading: "Security alerts from attacked networks",
  },
  rcaeval: {
    id: "ev-rcaeval",
    title: "Microservice shops with injected code faults",
    label: "Microservice code faults",
    heading: "Code-level faults in microservice shops",
  },
  anomod: {
    id: "ev-anomod",
    title: "Microservice systems with injected anomalies",
    label: "Microservice anomalies",
    heading: "Anomalies at four levels in two microservice systems",
  },
  itbench: {
    id: "ev-itbench",
    title: "Kubernetes incidents",
    label: "Kubernetes incidents",
    heading: "Kubernetes incidents",
  },
  jira: {
    id: "ev-jira",
    title: "Jira issues with priorities people set",
    label: "Jira priorities",
    heading: "Ticket priority in public issue trackers",
  },
  nezha: {
    id: "ev-nezha",
    title: "Faults injected into an online shop's pods",
    label: "Online shop pod faults",
    heading: "Faults injected into a shop's pods",
  },
};

/** "#security-alerts-from-attacked-networks": a heading's anchor, as GitHub names it. */
export function writeUpAnchor(heading: string): string {
  return `#${heading
    .toLowerCase()
    .replace(/[^\p{L}\p{M}\p{N}\p{Pc} -]/gu, "")
    .replace(/ /g, "-")}`;
}

/** What the tests on new domains measure between them, in the order the page says it. */
export type Aspect = "notice" | "rank" | "name" | "priority";
const ASPECTS: Record<DomainKey, Aspect[]> = {
  "ait-ads": ["notice", "rank"],
  rcaeval: ["notice", "rank", "name"],
  anomod: ["notice", "name"],
  itbench: ["notice", "name"],
  jira: ["priority"],
  nezha: ["notice", "rank", "name"],
};
const ORDER: Aspect[] = ["notice", "rank", "name", "priority"];

export const domainAspects = (results: DomainResult[]): Aspect[] =>
  ORDER.filter((aspect) => results.some((r) => ASPECTS[r.key].includes(aspect)));

// The microservice systems, as the data keys them (report_domains.py's _SYSTEMS).
const SYSTEMS: Record<string, string> = {
  SS: "Sock Shop",
  OB: "Online Boutique",
  TT: "Train Ticket",
  SN: "SocialNetwork",
};
export const serviceSystem = (key: string) => SYSTEMS[key] ?? key;

// The attack steps (report_domains.py's _STEPS), and each as a sentence names one.
const STEPS: Record<string, [name: string, inSentence: string]> = {
  network_scans: ["Network scans", "a network scan"],
  service_scans: ["Service scans", "a service scan"],
  dirb: ["Directory brute force", "a directory brute force"],
  wpscan: ["WordPress scan", "a WordPress scan"],
  webshell: ["Web shell upload", "a web shell upload"],
  cracking: ["Password cracking", "password cracking"],
  reverse_shell: ["Reverse shell", "a reverse shell"],
  privilege_escalation: ["Privilege escalation", "a privilege escalation"],
  service_stop: ["Stopped service", "a stopped service"],
  dnsteal: ["Data theft over DNS", "data theft over DNS"],
};
export const stepName = (key: string) => STEPS[key]?.[0] ?? key.replaceAll("_", " ");

// Nezha's kinds of fault.
const FAULTS: Record<string, string> = {
  cpu_consumed: "CPU consumption",
  cpu_contention: "CPU contention",
  network_delay: "network delay",
  exception: "exception",
  return: "wrong return value",
};
export const faultName = (key: string) => FAULTS[key] ?? key.replaceAll("_", " ");

export const ALERT_METHODS: Record<string, string> = {
  aria: "ARIA, end to end",
  rules_only: "ARIA's rules alone",
  model_only: "ARIA's model alone",
  keyword: "Keyword categories",
  ids_level: "The detectors' own alert level",
};
export const ALERT_SCORES: Record<string, string> = {
  aria_probability: "ARIA's probability of SEV1-2",
  aria_level: "ARIA's level",
  rules_only: "ARIA's rules alone",
  alert_count: "Number of alerts",
  keyword: "Keyword categories",
  ids_level: "The detectors' highest alert level",
};
// The simple scores ARIA's ranking is held against, as a sentence names them.
const ALERT_RIVALS: Record<string, string> = {
  alert_count: "counting the alerts",
  keyword: "keyword matching",
  ids_level: "the detectors' own alert level",
};
export const PRIORITY_METHODS: Record<string, string> = {
  aria: "ARIA's ticket model",
  at_open: "The priority it opened with",
  majority_class: "The commonest level",
  by_issue_type: "The commonest level for the issue's type",
};

const per100 = (x: number) => Math.round(x * 100);
const n = (x: number) => x.toLocaleString("en");
const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
const list = (items: string[], type: "conjunction" | "disjunction" = "conjunction") =>
  new Intl.ListFormat("en-GB", { type }).format(items);
const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** "about 3 in 10 of the steps", "none of the steps", "all of the steps". */
function ofThe(share: number, noun: string): string {
  const part = inTen(share);
  return part === "no" ? `none of the ${noun}` : `${part} of the ${noun}`;
}

/** How a ranking does, in words: never better than chance while its interval reaches 0.5. */
export function rankWords({ auroc, ci }: Ranking): string {
  if (ci[1] < 0.5) return "worse than chance";
  if (ci[0] <= 0.5) return "not clearly better than chance";
  if (auroc < 0.65) return "only a little better than chance";
  if (auroc < 0.75) return "fairly well";
  return auroc < 0.85 ? "well" : "very well";
}
/** Good enough to say so: clearly above chance, and right in at least 65 pairs in 100. */
const ranksWell = (r: Ranking) => r.ci[0] > 0.5 && r.auroc >= 0.65;
/** In how many pairs of 100 a score put the case that matters first. */
const pairs = (r: Ranking) => per100(r.auroc);

/** A figure as Test results shows one: [label, value, note under it]. */
export type Fact = [label: string, value: string, note?: string];

const interval = ([low, high]: [number, number]) => `95% interval ${pct(low)} to ${pct(high)}`;
const shareFact = (label: string, r: Rate): Fact => [
  label,
  pct(r.share),
  `${n(r.hits)} of ${n(r.of)}; ${interval(r.ci)}`,
];
const rankFact = (label: string, r: Ranking): Fact => [
  label,
  r.auroc.toFixed(3),
  `95% interval ${r.ci[0].toFixed(3)} to ${r.ci[1].toFixed(3)}`,
];
const missFact = (label: string, m: MissRate): Fact => [
  label,
  `${n(m.hits)} of ${n(m.of)}`,
  `At most ${pct(m.upper)}, with 95% confidence`,
];

/** "19 of 66 (29%)": a share as a table cell. */
export const cell = (r: Rate) => `${n(r.hits)} of ${n(r.of)} (${per100(r.share)}%)`;
/** "0.579 (0.503 to 0.656)": a ranking as a table cell. */
export const rankCell = (r: Ranking) =>
  `${r.auroc.toFixed(3)} (${r.ci[0].toFixed(3)} to ${r.ci[1].toFixed(3)})`;

/** A random pick's expected share as a sentence gives it. */
const byChance = (share: number) => `about ${per100(share)} in 100`;
/** "3 of 90 cases", or "none of the 17 runs". */
const outOf = (r: Rate, noun: string) =>
  r.hits === 0 ? `none of the ${n(r.of)} ${noun}` : `${n(r.hits)} of ${n(r.of)} ${noun}`;

// --- security alerts ---------------------------------------------------------------------------

const ariaAlerts = (s: SecurityAlerts) => s.methods.find((m) => m.key === "aria") ?? s.methods[0];

/** The simple scores that rank attack stretches, strongest first. */
const alertRivals = (s: SecurityAlerts) =>
  s.rankings.filter((r) => r.key in ALERT_RIVALS).sort((a, b) => b.ranking.auroc - a.ranking.auroc);

export function alertsVerdict(s: SecurityAlerts): string {
  const good = ranksWell(s.ranking);
  const lead = `ARIA tells attack stretches from routine alerts ${rankWords(s.ranking)}`;
  const [rival] = alertRivals(s);
  const versus = !rival
    ? ""
    : pairs(rival.ranking) > pairs(s.ranking)
      ? `, ${good ? "but" : "and"} ${ALERT_RIVALS[rival.key]} does better`
      : `, ${good ? "and" : "but"} at least as well as ${ALERT_RIVALS[rival.key]}`;
  return `${lead}${versus}; it pages ${ofThe(1 - s.harmfulMissed.share, "attack steps that do harm")}.`;
}

export function alertsResult(s: SecurityAlerts): string {
  const aria = ariaAlerts(s);
  const paged = aria
    ? `ARIA paged ${n(aria.attackPaged.hits)} of ${n(aria.attackPaged.of)} attack stretches and ${n(aria.routinePaged.hits)} of ${n(aria.routinePaged.of)} routine ones. `
    : "";
  const rivals = alertRivals(s).map(
    (r, i) => `${ALERT_RIVALS[r.key]}${i === 0 ? " did" : ""} in ${pairs(r.ranking)}`,
  );
  return `${paged}Shown one attack stretch and one routine one, its score ranked the attack first in ${pairs(s.ranking)} of 100 pairs (50 is a coin flip)${rivals.length ? `; ${list(rivals)}` : ""}.`;
}

export function alertsShortfall(s: SecurityAlerts): string | null {
  const missed = s.harmfulMissed;
  if (missed.hits > 0) {
    const never = s.steps
      .filter((t) => t.harmful && t.occurrences > 0 && t.paged === 0)
      .map((t) => STEPS[t.key]?.[1] ?? t.key.replaceAll("_", " "));
    const lead = never.length ? `It never paged ${list(never, "disjunction")}: in all, ` : "";
    const d = s.detectorsMissed;
    const detectors = d
      ? `; the detectors' own alert level missed ${d.hits === d.of ? "all of them" : n(d.hits)}`
      : "";
    return `${capital(`${lead}${n(missed.hits)} of ${n(missed.of)} harmful attack steps went unpaged, at most ${per100(missed.upper)} in 100 with 95% confidence`)}${detectors}.`;
  }
  const [rival] = alertRivals(s);
  if (rival && pairs(rival.ranking) > pairs(s.ranking)) {
    return `${capital(ALERT_RIVALS[rival.key] ?? rival.key)} ranked attack stretches above routine ones more often than ARIA's score: in ${pairs(rival.ranking)} pairs of 100, against ${pairs(s.ranking)}.`;
  }
  const routine = ariaAlerts(s)?.routinePaged;
  return routine && routine.share >= 0.05
    ? `It paged ${n(routine.hits)} of ${n(routine.of)} routine stretches.`
    : null;
}

export function alertsFacts(s: SecurityAlerts): Fact[] {
  const aria = ariaAlerts(s);
  return [
    ...(aria
      ? [
          shareFact("Attack stretches paged (SEV1-2)", aria.attackPaged),
          shareFact("Routine stretches paged", aria.routinePaged),
        ]
      : []),
    rankFact("Attack ranked above routine (AUROC)", s.ranking),
  ];
}

// --- faults injected one at a time (RCAEval, Nezha) ---------------------------------------------

export function faultVerdict(s: FaultWindows): string {
  const { faulty, healthy } = s.aria;
  const caught =
    faulty.hits === faulty.of
      ? "the logs after every fault"
      : `the logs after ${inTen(faulty.share)} faults`;
  const alarms =
    healthy.hits === 0
      ? "and none of the healthy logs before them"
      : `${healthy.share < 0.1 ? "and" : "but also"} ${ofThe(healthy.share, "healthy logs before them")}`;
  const e = s.anyError;
  const rival =
    e.faulty.hits === faulty.hits && e.healthy.hits === healthy.hits
      ? "exactly as an alert on any error line does"
      : faulty.hits >= e.faulty.hits && healthy.hits <= e.healthy.hits
        ? "doing better than an alert on any error line"
        : faulty.hits <= e.faulty.hits && healthy.hits >= e.healthy.hits
          ? "doing worse than an alert on any error line"
          : "striking a different balance from an alert on any error line";
  return `ARIA flags ${caught}, ${alarms}, ${rival}.`;
}

export function faultResult(s: FaultWindows): string {
  const { faulty, healthy, ranking } = s.aria;
  const e = s.anyError;
  return `ARIA flagged ${n(faulty.hits)} of ${n(faulty.of)} faulty stretches and ${n(healthy.hits)} of ${n(healthy.of)} healthy ones; an alert on any error line flagged ${n(e.faulty.hits)} and ${n(e.healthy.hits)}. Shown a faulty stretch and a healthy one, ARIA's score ranked the faulty one first in ${pairs(ranking)} of 100 pairs (50 is a coin flip), and counting error lines did in ${pairs(s.errorRanking)}.`;
}

export function faultShortfall(s: FaultWindows): string | null {
  const unseen = s.faults.filter((f) => f.cases > 0 && f.flagged.hits === 0);
  if (unseen.length && unseen.every((f) => f.key in FAULTS)) {
    const cases = unseen.reduce((total, f) => total + f.cases, 0);
    return `It flagged none of the ${list(
      unseen.map((f) => faultName(f.key)),
      "disjunction",
    )} faults: ${n(cases)} of ${n(s.cases)} went unnoticed.`;
  }
  const { naming, healthy, ranking } = s.aria;
  if (per100(naming.first.share) < per100(s.random.first)) {
    return `Its first suspect was the service at fault in ${outOf(naming.first, "cases")}, fewer than a random pick would get (${byChance(s.random.first)}).`;
  }
  if (per100(naming.firstThree.share) < per100(s.random.firstThree)) {
    return `The service at fault was among its first three suspects in ${outOf(naming.firstThree, "cases")}, fewer than a random pick would get (${byChance(s.random.firstThree)}).`;
  }
  if (healthy.share >= 0.1) {
    return `It also flagged ${n(healthy.hits)} of ${n(healthy.of)} healthy stretches.`;
  }
  return pairs(s.errorRanking) > pairs(ranking)
    ? `Counting error lines ranked faulty stretches above healthy ones more often than ARIA's score: in ${pairs(s.errorRanking)} pairs of 100, against ${pairs(ranking)}.`
    : null;
}

export function faultFacts(s: FaultWindows): Fact[] {
  return [
    shareFact("Faulty stretches flagged", s.aria.faulty),
    shareFact("Healthy stretches flagged", s.aria.healthy),
    shareFact("Service at fault among the first three suspects", s.aria.naming.firstThree),
  ];
}

// --- anomalies in microservice systems (AnoMod) -------------------------------------------------

/** "both normal runs", "the normal run", "all three normal runs", "one of the two normal runs". */
function normalRuns(flagged: number, normal: number): string {
  if (normal === 1) return "the normal run";
  if (flagged !== normal) return `${words(flagged)} of the ${words(normal)} normal runs`;
  return normal === 2 ? "both normal runs" : `all ${words(normal)} normal runs`;
}

export function anomaliesVerdict(s: Anomalies): string {
  const lead =
    s.flagged.hits === s.flagged.of
      ? "ARIA flags every anomalous run"
      : `ARIA flags ${inTen(s.flagged.share)} anomalous runs`;
  const e = s.anyError.flagged.hits;
  const rival =
    e === s.flagged.hits
      ? "as an alert on any error line does"
      : e > s.flagged.hits
        ? "fewer than an alert on any error line"
        : "more than an alert on any error line";
  const normal =
    s.normalFlagged === 0
      ? `and it left ${normalRuns(s.normal, s.normal)} alone`
      : `but it also flagged ${normalRuns(s.normalFlagged, s.normal)}`;
  const few = s.normal < 10 ? ", too few to say how often it raises false alarms" : "";
  return `${lead}, ${rival}, ${normal}${few}.`;
}

export function anomaliesResult(s: Anomalies): string {
  const levels = s.normalLevels.map(
    (l, i) => `${serviceSystem(l.system)}'s${i === 0 ? " normal run" : ""} ${l.level}`,
  );
  return `ARIA flagged ${n(s.flagged.hits)} of ${n(s.flagged.of)} anomalous runs and paged ${n(s.paged.hits)}; an alert on any error line flagged ${n(s.anyError.flagged.hits)}.${levels.length ? ` It rated ${list(levels)}.` : ""}`;
}

export function anomaliesShortfall(s: Anomalies): string | null {
  const { first, firstThree } = s.naming;
  if (per100(firstThree.share) < per100(s.random.firstThree)) {
    return `The targeted service was among its first three suspects in ${outOf(firstThree, "runs")}, fewer than a random pick would get (${byChance(s.random.firstThree)}).`;
  }
  if (per100(first.share) < per100(s.random.first)) {
    return `Its first suspect was the targeted service in ${outOf(first, "runs")}, fewer than a random pick would get (${byChance(s.random.first)}).`;
  }
  if (s.normalFlagged > 0) {
    return `It flagged ${normalRuns(s.normalFlagged, s.normal)}, which had nothing wrong.`;
  }
  return s.paged.share < 0.5
    ? `It paged only ${n(s.paged.hits)} of ${n(s.paged.of)} anomalous runs.`
    : null;
}

export function anomaliesFacts(s: Anomalies): Fact[] {
  return [
    shareFact("Anomalous runs flagged", s.flagged),
    shareFact("Anomalous runs paged", s.paged),
    shareFact("Targeted service among the first three suspects", s.naming.firstThree),
  ];
}

// --- Kubernetes incidents (ITBench) -------------------------------------------------------------

export function kubernetesVerdict(s: KubernetesIncidents): string {
  const share = (x: number) => (inTen(x) === "no" ? "none" : inTen(x));
  const ours = per100(s.naming.firstThree.share);
  const theirs = per100(s.alertedServices.firstThree.share);
  const naming =
    ours > theirs
      ? "and it names the service at fault among its first three suspects more often than the alerts do"
      : ours === theirs
        ? "and it names the service at fault among its first three suspects as often as the alerts do"
        : "but the alerts name the service at fault more often than it does";
  return `ARIA pages ${share(s.paged.share)} Kubernetes incidents, where the alerts' own severity pages ${share(s.alerts.paged.share)}, ${naming}.`;
}

export function kubernetesResult(s: KubernetesIncidents): string {
  const named = s.naming.firstThree;
  return `ARIA flagged ${n(s.flagged.hits)} of ${n(s.flagged.of)} incidents and paged ${n(s.paged.hits)}; the alerts' own severity flagged ${n(s.alerts.flagged.hits)} and paged ${n(s.alerts.paged.hits)}. The service at fault was among ARIA's first three suspects in ${n(named.hits)} of ${n(named.of)}, against ${n(s.alertedServices.firstThree.hits)} for the services the alerts name and ${byChance(s.random.firstThree)} for a random pick.`;
}

export function kubernetesShortfall(s: KubernetesIncidents): string | null {
  const { first, firstThree } = s.naming;
  if (per100(first.share) < per100(s.random.first)) {
    return `Its first suspect was the service at fault in ${outOf(first, "incidents")}, fewer than a random pick would get (${byChance(s.random.first)}).`;
  }
  if (s.missed.hits > 0) {
    return `It rated ${n(s.missed.hits)} of ${n(s.missed.of)} incidents SEV4, as if nothing were wrong: at most ${per100(s.missed.upper)} in 100, with 95% confidence.`;
  }
  return per100(firstThree.share) < per100(s.random.firstThree)
    ? `The service at fault was among its first three suspects in ${outOf(firstThree, "incidents")}, fewer than a random pick would get (${byChance(s.random.firstThree)}).`
    : null;
}

export function kubernetesFacts(s: KubernetesIncidents): Fact[] {
  return [
    shareFact("Incidents paged (SEV1-2)", s.paged),
    missFact("Incidents missed (rated SEV4)", s.missed),
    shareFact("Service at fault among the first three suspects", s.naming.firstThree),
  ];
}

// --- Jira priorities -----------------------------------------------------------------------------

export const priorityMethod = (t: Tracker, key: string): PriorityMethod | undefined =>
  t.methods.find((m) => m.key === key);

/** ARIA's result on every tracker's issues together; the reader keeps a suite only with it. */
const ariaPriority = (s: IssuePriority) =>
  priorityMethod(s.pooled, "aria") ?? (s.pooled.methods[0] as PriorityMethod);

/** "each tracker's commonest level" where there are several trackers. */
const commonest = (s: IssuePriority) =>
  s.trackers.length > 1 ? "each tracker's commonest level" : "the commonest level";

export function priorityVerdict(s: IssuePriority): string {
  const aria = ariaPriority(s);
  const common = priorityMethod(s.pooled, "majority_class");
  const versus = !common
    ? ""
    : per100(aria.accuracy) < per100(common.accuracy)
      ? ` less often than always picking ${commonest(s)}`
      : per100(aria.accuracy) === per100(common.accuracy)
        ? ` no more often than always picking ${commonest(s)}`
        : ` more often than always picking ${commonest(s)}`;
  const urgent = aria.urgentMissed;
  const misses =
    urgent.hits === urgent.of
      ? "it misses every urgent issue"
      : urgent.hits === 0
        ? "it misses no urgent issue"
        : `it misses ${inTen(urgent.share)} urgent issues`;
  const joiner = urgent.share >= 0.5 === (common != null && aria.accuracy < common.accuracy);
  return `On Jira, ARIA's ticket model sets the priority people chose${versus}, ${joiner ? "and" : "but"} ${misses}.`;
}

export function priorityResult(s: IssuePriority): string {
  const aria = ariaPriority(s);
  const common = priorityMethod(s.pooled, "majority_class");
  const atOpen = priorityMethod(s.pooled, "at_open");
  const where =
    s.trackers.length === 2
      ? "Across both trackers"
      : s.trackers.length > 2
        ? `Across all ${words(s.trackers.length)} trackers`
        : "On this tracker";
  const rivals = [
    ...(common ? [`always picking ${commonest(s)} got ${per100(common.accuracy)}`] : []),
    ...(atOpen ? [`keeping the priority an issue opened with got ${per100(atOpen.accuracy)}`] : []),
  ];
  return `${where}, ARIA's ticket model set the priority people chose for ${per100(aria.accuracy)} issues in 100${rivals.length ? `; ${list(rivals)}` : ""}.`;
}

export function priorityShortfall(s: IssuePriority): string | null {
  const aria = ariaPriority(s);
  const urgent = aria.urgentMissed;
  const [only, ...others] = Object.keys(aria.predicted);
  if (only && !others.length && urgent.of > 0 && urgent.hits === urgent.of) {
    return `It gave every issue the same level, ${only}, so all ${n(urgent.of)} urgent ones (levels 1 and 2) were rated too low.`;
  }
  if (urgent.share >= 0.5) {
    return `It rated ${n(urgent.hits)} of ${n(urgent.of)} urgent issues (levels 1 and 2) 3 or 4.`;
  }
  const common = priorityMethod(s.pooled, "majority_class");
  return common && per100(common.accuracy) > per100(aria.accuracy)
    ? `Always picking ${commonest(s)} was right more often: for ${per100(common.accuracy)} issues in 100, against ${per100(aria.accuracy)}.`
    : null;
}

export function priorityFacts(s: IssuePriority): Fact[] {
  const aria = ariaPriority(s);
  return [
    ["Right priority (accuracy)", pct(aria.accuracy), interval(aria.accuracyCi)],
    [
      "Balance across levels (macro-F1)",
      aria.macroF1.toFixed(3),
      `95% interval ${aria.macroF1Ci[0].toFixed(3)} to ${aria.macroF1Ci[1].toFixed(3)}`,
    ],
    shareFact("Urgent issues rated 3 or 4", aria.urgentMissed),
  ];
}

// --- every suite --------------------------------------------------------------------------------

/** A suite's verdict, result, shortfall and figures, whichever suite it is. */
export function domainSummary(d: DomainResult): {
  verdict: string;
  result: string;
  shortfall: string | null;
  facts: Fact[];
} {
  switch (d.key) {
    case "ait-ads":
      return {
        verdict: alertsVerdict(d),
        result: alertsResult(d),
        shortfall: alertsShortfall(d),
        facts: alertsFacts(d),
      };
    case "rcaeval":
    case "nezha":
      return {
        verdict: faultVerdict(d),
        result: faultResult(d),
        shortfall: faultShortfall(d),
        facts: faultFacts(d),
      };
    case "anomod":
      return {
        verdict: anomaliesVerdict(d),
        result: anomaliesResult(d),
        shortfall: anomaliesShortfall(d),
        facts: anomaliesFacts(d),
      };
    case "itbench":
      return {
        verdict: kubernetesVerdict(d),
        result: kubernetesResult(d),
        shortfall: kubernetesShortfall(d),
        facts: kubernetesFacts(d),
      };
    case "jira":
      return {
        verdict: priorityVerdict(d),
        result: priorityResult(d),
        shortfall: priorityShortfall(d),
        facts: priorityFacts(d),
      };
  }
}
