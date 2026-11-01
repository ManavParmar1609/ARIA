import { describe, expect, it } from "vitest";

import {
  readDomains,
  type Anomalies,
  type DomainResult,
  type FaultWindows,
  type IssuePriority,
  type KubernetesIncidents,
  type SecurityAlerts,
} from "@/lib/domains";
import * as raw from "@/test/domains";

import {
  alertsShortfall,
  alertsVerdict,
  anomaliesShortfall,
  anomaliesVerdict,
  cell,
  DOMAIN_CARDS,
  domainAspects,
  domainSummary,
  faultShortfall,
  faultVerdict,
  kubernetesShortfall,
  kubernetesVerdict,
  priorityShortfall,
  priorityVerdict,
  rankWords,
  writeUpAnchor,
} from "./domain-results";

/** One suite as the page reads it, from a summary shaped like `make eval`'s. */
const read = <T extends DomainResult>(key: T["key"], summary: unknown) =>
  readDomains({ [key]: summary })?.results[0] as T;

describe("the new-domain cards on Test results", () => {
  it("opens every card with one plain sentence, written from the results", () => {
    const results = readDomains(raw.domains())?.results ?? [];
    expect(results).toHaveLength(6);
    for (const result of results) {
      const { verdict, result: numbers, shortfall, facts } = domainSummary(result);
      // One sentence: a capital first, one full stop, at the end.
      expect(verdict).toMatch(/^[A-Z][^.]*[^.\s]\.$/);
      for (const text of [verdict, numbers, shortfall ?? ""]) {
        expect(text).not.toMatch(/undefined|NaN|null|Infinity/);
      }
      expect(numbers).toMatch(/\.$/);
      expect(shortfall).toMatch(/^[A-Z].*\.$/);
      // The two or three numbers that matter, each with its interval or bound under it.
      expect(facts).toHaveLength(3);
      for (const [, , note] of facts) expect(note).toMatch(/95%/);
    }
  });

  it("never calls a ranking better than chance while its interval reaches a coin flip", () => {
    expect(rankWords({ auroc: 0.4, ci: [0.3, 0.48] })).toBe("worse than chance");
    expect(rankWords({ auroc: 0.58, ci: [0.49, 0.66] })).toBe("not clearly better than chance");
    expect(rankWords({ auroc: 0.6, ci: [0.55, 0.65] })).toBe("only a little better than chance");
    expect(rankWords({ auroc: 0.71, ci: [0.64, 0.78] })).toBe("fairly well");
    expect(rankWords({ auroc: 0.81, ci: [0.75, 0.87] })).toBe("well");
    expect(rankWords({ auroc: 0.9, ci: [0.85, 0.95] })).toBe("very well");
  });

  it("says whether a simple score ranks attacks better than ARIA, whichever way it goes", () => {
    expect(alertsVerdict(read<SecurityAlerts>("ait-ads", raw.alerts()))).toBe(
      "ARIA tells attack stretches from routine alerts only a little better than chance, and counting the alerts does better; it pages about 4 in 10 of the attack steps that do harm.",
    );
    const even = raw.alerts();
    even.ranking.alert_count = raw.auroc(0.55);
    expect(alertsVerdict(read<SecurityAlerts>("ait-ads", even))).toContain(
      "only a little better than chance, but at least as well as keyword matching;",
    );
    const strong = raw.alerts();
    strong.ranking.aria_probability = raw.auroc(0.8);
    expect(alertsVerdict(read<SecurityAlerts>("ait-ads", strong))).toContain(
      "from routine alerts well, and at least as well as counting the alerts;",
    );
  });

  it("names the harmful attack steps ARIA never paged, beside the detectors' own level", () => {
    expect(alertsShortfall(read<SecurityAlerts>("ait-ads", raw.alerts()))).toBe(
      "It never paged a reverse shell or a privilege escalation: in all, 10 of 16 harmful attack steps went unpaged, at most 75 in 100 with 95% confidence; the detectors' own alert level missed all of them.",
    );
    // With no harmful step missed, the shortfall is the next weakest point: the ranking.
    const paged = raw.alerts();
    paged.steps.aria.severe_miss = raw.miss(0, 16);
    expect(alertsShortfall(read<SecurityAlerts>("ait-ads", paged))).toBe(
      "Counting the alerts ranked attack stretches above routine ones more often than ARIA's score: in 70 pairs of 100, against 60.",
    );
  });

  it("holds ARIA's flags on injected faults against an alert on any error line", () => {
    expect(faultVerdict(read<FaultWindows>("rcaeval", raw.faults()))).toBe(
      "ARIA flags the logs after every fault, but also about 4 in 10 of the healthy logs before them, exactly as an alert on any error line does.",
    );
    const noisier = raw.faults();
    noisier.baselines.any_error_line.healthy_flagged = raw.share(30, 40);
    expect(faultVerdict(read<FaultWindows>("rcaeval", noisier))).toMatch(
      /doing better than an alert on any error line\.$/,
    );
    const quiet = raw.faults({ faulty: 4, healthy: 0, byFault: true });
    expect(faultVerdict(read<FaultWindows>("nezha", quiet))).toBe(
      "ARIA flags the logs after about 1 in 10 faults, and none of the healthy logs before them, exactly as an alert on any error line does.",
    );
  });

  it("says which kinds of fault went unnoticed, or else how often it named the service at fault", () => {
    const pods = raw.faults({ faulty: 4, healthy: 0, byFault: true });
    expect(faultShortfall(read<FaultWindows>("nezha", pods))).toBe(
      "It flagged none of the CPU contention faults: 20 of 40 went unnoticed.",
    );
    expect(faultShortfall(read<FaultWindows>("rcaeval", raw.faults()))).toBe(
      "Its first suspect was the service at fault in 2 of 40 cases, fewer than a random pick would get (about 8 in 100).",
    );
    expect(faultShortfall(read<FaultWindows>("rcaeval", raw.faults({ first: 0 })))).toContain(
      "in none of the 40 cases,",
    );
  });

  it("says plainly when a test has too few healthy runs to count false alarms", () => {
    expect(anomaliesVerdict(read<Anomalies>("anomod", raw.anomalies()))).toBe(
      "ARIA flags every anomalous run, as an alert on any error line does, but it also flagged both normal runs, too few to say how often it raises false alarms.",
    );
    const calm = raw.anomalies();
    calm.aria.normal_flagged = 0;
    expect(anomaliesVerdict(read<Anomalies>("anomod", calm))).toContain(
      "and it left both normal runs alone, too few",
    );
    expect(anomaliesShortfall(read<Anomalies>("anomod", raw.anomalies()))).toBe(
      "The targeted service was among its first three suspects in none of the 6 runs, fewer than a random pick would get (about 18 in 100).",
    );
  });

  it("compares paging and naming on Kubernetes incidents with what the alerts say", () => {
    const incidents = read<KubernetesIncidents>("itbench", raw.incidents());
    expect(kubernetesVerdict(incidents)).toBe(
      "ARIA pages about 9 in 10 Kubernetes incidents, where the alerts' own severity pages about 1 in 10, and it names the service at fault among its first three suspects more often than the alerts do.",
    );
    expect(kubernetesShortfall(incidents)).toBe(
      "Its first suspect was the service at fault in none of the 19 incidents, fewer than a random pick would get (about 6 in 100).",
    );
    const alerted = raw.incidents();
    alerted.baselines.naming_alerted_service = {
      ...alerted.baselines.naming_alerted_service,
      top3: raw.share(12, 19),
    };
    expect(kubernetesVerdict(read<KubernetesIncidents>("itbench", alerted))).toMatch(
      /but the alerts name the service at fault more often than it does\.$/,
    );
  });

  it("says when the ticket model misses every urgent issue by giving all one level", () => {
    const jira = read<IssuePriority>("jira", raw.priorities());
    expect(priorityVerdict(jira)).toBe(
      "On Jira, ARIA's ticket model sets the priority people chose less often than always picking each tracker's commonest level, and it misses every urgent issue.",
    );
    expect(priorityShortfall(jira)).toBe(
      "It gave every issue the same level, 3, so all 100 urgent ones (levels 1 and 2) were rated too low.",
    );
  });

  it("writes whole sentences when a baseline is missing from the results", () => {
    const alerts = raw.alerts();
    const { ids_level: _detectors, ...steps } = alerts.steps;
    const plain = read<SecurityAlerts>("ait-ads", { ...alerts, steps });
    expect(alertsShortfall(plain)).toMatch(/with 95% confidence\.$/);
    const jira = raw.priorities();
    const { majority_class: _common, ...methods } = jira.pooled.methods;
    const alone = read<IssuePriority>("jira", { ...jira, pooled: { ...jira.pooled, methods } });
    expect(priorityVerdict(alone)).toBe(
      "On Jira, ARIA's ticket model sets the priority people chose, but it misses every urgent issue.",
    );
  });

  it("never writes a share in a table as none or all when it is not", () => {
    const rate = (hits: number, of: number) => ({
      hits,
      of,
      share: hits / of,
      ci: [0, 1] as [number, number],
    });
    expect(cell(rate(10, 2683))).toBe("10 of 2,683 (under 1%)");
    expect(cell(rate(1999, 2000))).toBe("1,999 of 2,000 (over 99%)");
    expect(cell(rate(0, 56))).toBe("0 of 56 (0%)");
    expect(cell(rate(90, 90))).toBe("90 of 90 (100%)");
    expect(cell(rate(19, 66))).toBe("19 of 66 (29%)");
  });

  it("links each card to its section of the full write-up, as GitHub names it", () => {
    expect(writeUpAnchor(DOMAIN_CARDS.nezha.heading)).toBe("#faults-injected-into-a-shops-pods");
    expect(writeUpAnchor(DOMAIN_CARDS.rcaeval.heading)).toBe(
      "#code-level-faults-in-microservice-shops",
    );
    expect(writeUpAnchor(DOMAIN_CARDS["ait-ads"].heading)).toBe(
      "#security-alerts-from-attacked-networks",
    );
  });

  it("says what the tests measure between them, from the suites that ran", () => {
    const all = readDomains(raw.domains())?.results ?? [];
    expect(domainAspects(all)).toEqual(["notice", "rank", "name", "priority"]);
    expect(domainAspects(all.filter((r) => r.key === "jira"))).toEqual(["priority"]);
  });
});
