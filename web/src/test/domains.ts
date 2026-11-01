// Results shaped like `make eval`'s "domains" and "registry" objects, for unit tests. The numbers
// are made up, not measured: tests change them to check each verdict both ways.

/** A part of a group as the results write it, with an interval around it. */
export function share(hits: number, of: number) {
  const s = of ? hits / of : 0;
  const round = (x: number) => Math.round(x * 10000) / 10000;
  return {
    hits,
    of,
    share: round(s),
    ci95: [round(Math.max(0, s - 0.1)), round(Math.min(1, s + 0.1))],
  };
}

/** A miss rate, with its one-sided bound. */
export const miss = (hits: number, of: number) => ({
  ...share(hits, of),
  upper95: Math.min(1, Math.round((hits / of + 0.12) * 10000) / 10000),
});

export const auroc = (value: number) => ({
  auroc: value,
  auroc_ci95: [value - 0.05, value + 0.05],
  positives: 20,
  n: 200,
});

const naming = (first: number, firstThree: number, of: number) => ({
  top1: share(first, of),
  top3: share(firstThree, of),
  named_anywhere: share(firstThree, of),
});

const stamp = { ring: "C", tuning: "no rule was changed for this data" };

const step = (occurrences: number, flagged: number, paged: number) => ({
  occurrences,
  with_alerts: occurrences,
  flagged,
  paged,
});

export function alerts() {
  const rates = (attackPaged: number, routinePaged: number) => ({
    attack_flagged: share(attackPaged + 4, 40),
    attack_paged: share(attackPaged, 40),
    routine_flagged: share(routinePaged + 30, 1000),
    routine_paged: share(routinePaged, 1000),
  });
  return {
    source: "an alert data set",
    citation: "A. Author. An alert data set. 2024.",
    stamp,
    window_min: 20,
    scenarios: 4,
    windows: 1040,
    attack_windows: 40,
    routine_windows: 1000,
    alerts: 120000,
    line_cap: 20000,
    windows_over_line_cap: 2,
    ranking: {
      aria_probability: auroc(0.6),
      aria_level: auroc(0.62),
      ids_level: auroc(0.52),
      alert_count: auroc(0.7),
      keyword: auroc(0.6),
      rules_only: auroc(0.61),
    },
    per_scenario_auroc: { median: 0.58, worst: 0.52, below_0_5: 0 },
    rates: {
      aria: rates(8, 4),
      rules_only: rates(8, 3),
      model_only: rates(7, 1),
      keyword: rates(7, 0),
      ids_level: rates(0, 0),
    },
    steps: {
      aria: {
        by_step: {
          network_scans: step(4, 4, 4),
          webshell: step(4, 4, 4),
          cracking: step(4, 3, 2),
          reverse_shell: step(4, 0, 0),
          privilege_escalation: step(4, 0, 0),
        },
        harmful_occurrences: 16,
        harmful_without_alerts: 0,
        severe_miss: miss(10, 16),
        harmful_flagged: share(7, 16),
      },
      ids_level: {
        by_step: {},
        harmful_occurrences: 16,
        harmful_without_alerts: 0,
        severe_miss: miss(16, 16),
        harmful_flagged: share(12, 16),
      },
    },
  };
}

/** Faults injected one at a time, as RCAEval and Nezha report them. */
export function faults(
  options: { faulty?: number; healthy?: number; first?: number; byFault?: boolean } = {},
) {
  const { faulty = 40, healthy = 16, first = 2, byFault = false } = options;
  const naming40 = naming(first, 15, 40);
  return {
    source: "a fault data set",
    citation: "B. Author. A fault benchmark. 2025.",
    stamp,
    cases: 40,
    windows: 80,
    by_system: { OB: 20, SS: 20 },
    lines: 900000,
    line_cap: 20000,
    windows_over_line_cap: 60,
    ...(byFault ? { window_min: 1, days: ["2022-08-22", "2022-08-23"] } : {}),
    aria: {
      faulty_flagged: share(faulty, 40),
      healthy_flagged: share(healthy, 40),
      paged: {
        faulty_flagged: share(Math.round(faulty * 0.6), 40),
        healthy_flagged: share(healthy, 40),
      },
      paired: { higher: 25, same: 12, lower: 3 },
      ranking: auroc(0.7),
      naming: naming40,
    },
    baselines: {
      any_error_line: { faulty_flagged: share(faulty, 40), healthy_flagged: share(healthy, 40) },
      error_count_ranking: auroc(0.8),
      naming_most_errors: naming(3, 14, 40),
      naming_most_changed: naming(14, 26, 40),
      naming_random_expected: { top1: 0.08, top3: 0.24 },
    },
    by_system_detail: {
      OB: {
        cases: 20,
        faulty_flagged: share(20, 20),
        healthy_flagged: share(0, 20),
        naming: naming(1, 9, 20),
      },
      SS: {
        cases: 20,
        faulty_flagged: share(20, 20),
        healthy_flagged: share(16, 20),
        naming: naming(1, 6, 20),
      },
    },
    by_fault: byFault
      ? {
          cpu_contention: {
            cases: 20,
            faulty_flagged: share(0, 20),
            healthy_flagged: share(0, 20),
            naming: naming(0, 0, 20),
          },
          exception: {
            cases: 20,
            faulty_flagged: share(faulty, 20),
            healthy_flagged: share(0, 20),
            naming: naming(first, first, 20),
          },
        }
      : {
          f1: {
            cases: 40,
            faulty_flagged: share(faulty, 40),
            healthy_flagged: share(healthy, 40),
            naming: naming40,
          },
        },
    found: 40,
  };
}

export function anomalies() {
  return {
    source: "an anomaly data set",
    citation: "C. Author. An anomaly data set. 2026.",
    stamp,
    runs: 10,
    anomalous: 8,
    normal: 2,
    by_system: { SN: 5, TT: 5 },
    line_cap: 20000,
    aria: {
      anomalous_flagged: share(8, 8),
      anomalous_paged: share(4, 8),
      normal_flagged: 2,
      normal_severity: { SN: "SEV3", TT: "SEV2" },
      naming: naming(0, 0, 6),
    },
    baselines: {
      any_error_line: { anomalous_flagged: share(8, 8), normal_flagged: 2 },
      naming_most_errors: naming(1, 1, 6),
      naming_random_expected: { top1: 0.06, top3: 0.18 },
    },
    by_level: {
      code: { runs: 4, flagged: share(4, 4), severity: { SEV1: 0, SEV2: 2, SEV3: 2, SEV4: 0 } },
      service: { runs: 4, flagged: share(4, 4), severity: { SEV1: 0, SEV2: 2, SEV3: 2, SEV4: 0 } },
    },
  };
}

export function incidents() {
  return {
    source: "an incident benchmark",
    citation: "D. Author. An incident benchmark. 2025.",
    stamp,
    scenarios: 20,
    window_min: 10,
    lines: 400000,
    line_cap: 20000,
    with_named_service: 19,
    aria: {
      flagged: share(19, 20),
      paged: share(18, 20),
      missed: miss(1, 20),
      naming: naming(0, 8, 19),
    },
    baselines: {
      alert_severity: { flagged: share(20, 20), paged: share(2, 20) },
      any_error_line: share(18, 20),
      naming_alerted_service: naming(1, 3, 19),
      naming_most_errors: naming(0, 2, 19),
      naming_random_expected: { top1: 0.06, top3: 0.18 },
    },
    found: 21,
  };
}

const priority = (accuracy: number, urgentMissed: number, predicted: Record<string, number>) => ({
  accuracy,
  accuracy_ci95: [accuracy - 0.01, accuracy + 0.01],
  macro_f1: accuracy / 3,
  macro_f1_ci95: [accuracy / 3 - 0.01, accuracy / 3 + 0.01],
  urgent_missed: miss(urgentMissed, 100),
  predicted,
});

const tracker = (tickets: number, majority: number) => ({
  tickets,
  levels: { "1": 40, "2": 60, "3": tickets - 300, "4": 200 },
  changed_after_open: share(Math.round(tickets / 20), tickets),
  methods: {
    aria: priority(majority - 0.2, 100, { "3": tickets }),
    at_open: priority(0.95, 20, { "1": 35, "2": 55, "3": tickets - 290, "4": 200 }),
    majority_class: priority(majority, 100, { "3": tickets }),
    by_issue_type: priority(majority, 100, { "3": tickets }),
  },
  set_coverage: majority - 0.2,
  mean_set_size: 1,
});

export function priorities() {
  return {
    source: "a public issue data set",
    citation: "E. Author. An issue data set. 2022.",
    stamp,
    reference_tickets: 7000,
    test_tickets: 3000,
    instances: { Apache: tracker(2000, 0.7), Jira: tracker(1000, 0.65) },
    pooled: tracker(3000, 0.68),
    decided_by: { model: 3000 },
  };
}

/** Every suite, in the order the results write them (not the page's). */
export function domains() {
  return {
    "ait-ads": alerts(),
    anomod: anomalies(),
    itbench: incidents(),
    jira: priorities(),
    nezha: faults({ faulty: 4, healthy: 0, first: 3, byFault: true }),
    rcaeval: faults(),
  };
}

export function registry() {
  const seen = (since?: string) => ({
    ring: "C",
    status: "seen",
    ...(since ? { since } : {}),
    note: "Looked at during development.",
  });
  return {
    suites: {
      severity: { ring: "A", status: "tuned", note: "Fresh windows of the training systems." },
      generalisation: {
        ring: "B",
        status: "tuned",
        since: "2026-11-01",
        note: "Each system held out in turn.",
      },
      "real.hdfs": seen(),
      "real.hadoop": {
        ring: "C",
        status: "tuned",
        since: "2026-11-01",
        note: "A rule changed after these jobs.",
      },
      "real.openstack": seen("2026-10-31"),
      "domains.ait-ads": seen("2026-11-01"),
      "domains.jira": seen("2026-11-01"),
    },
  };
}
