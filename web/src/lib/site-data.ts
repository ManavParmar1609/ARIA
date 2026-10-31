import "server-only";

import demo from "@/data/demo-run.json";
import evals from "@/data/eval-results.json";
import live from "@/data/eval-live.json";

import type { Severity } from "./api/types";

// Everything the landing page quotes comes from three committed files: the offline evaluation
// (docs/eval-results.json), the live-provider run (docs/eval-live.json) and one recorded run
// (scripts/record_demo_run.py). Nothing here is typed in by hand.

export const REPO_URL = "https://github.com/ManavParmar1609/ARIA";
export const EVAL_DOC_URL = `${REPO_URL}/blob/main/docs/evaluation.md`;

export interface ReplayLine {
  lineNo: number;
  text: string;
  level: string | null;
  templateId: string | null;
  quarantined: boolean;
}

export interface ReplayEvidence {
  id: string;
  kind: string;
  title: string;
  detail: string;
  lines: number[];
}

export interface ReplayClaim {
  text: string;
  evidence: string[];
}

export interface Replay {
  title: string;
  system: string;
  severity: Severity;
  probabilities: Record<Severity, number>;
  predictionSet: Severity[];
  /** True when no level cleared the bar: the set then holds the likeliest level as a stand-in. */
  setEmpty: boolean;
  decidedBy: string;
  needsReview: boolean;
  confidence: number;
  windowMinutes: number;
  lines: ReplayLine[];
  hiddenBefore: number;
  claims: ReplayClaim[];
  evidence: Record<string, ReplayEvidence>;
  nLines: number;
  timeToReviewMs: number;
  recordedAt: string;
  gitSha: string;
}

const stripSeverity = (title: string) => title.replace(/^SEV[1-4]\s*·\s*/, "");

/** The hero's replay: a slice of the real log, the tag's fields and the evidence behind them. */
export function replay(): Replay {
  const events = demo.batch.events;
  const report = demo.report;
  const evidence = Object.fromEntries(report.evidence.map((e) => [e.id, e]));
  const plantedLineNo = demo.input.planted_index + 1;

  // Template id -> the line numbers that carry it, so a template citation lights up its lines.
  const byTemplate = new Map<string, number[]>();
  for (const e of events) {
    if (e.line_no == null) continue;
    byTemplate.set(e.template_id, [...(byTemplate.get(e.template_id) ?? []), e.line_no]);
  }
  const linesFor = (id: string): number[] => {
    const e = evidence[id];
    if (!e) return [];
    const data = e.data as Record<string, unknown>;
    if (typeof data.line === "number") return [data.line];
    if (typeof data.template_id === "string") return byTemplate.get(data.template_id) ?? [];
    return [];
  };

  // Show the first incident line with a little context before it, then the planted line.
  const firstWarn = events.find((e) => e.level === "WARN")?.line_no ?? 1;
  const start = Math.max(1, firstWarn - 4);
  const shown: ReplayLine[] = events
    .filter((e) => e.line_no != null && e.line_no >= start && e.line_no < start + 9)
    .map((e) => ({
      lineNo: e.line_no ?? 0,
      text: e.message,
      level: e.level,
      templateId: e.template_id,
      quarantined: false,
    }));
  shown.push({
    lineNo: plantedLineNo,
    text: demo.input.planted_line.replace(/^.*?(INFO\s)/, "$1"),
    level: "INFO",
    templateId: null,
    quarantined: true,
  });

  const pick = (claim: { text: string; evidence_ids: string[] }): ReplayClaim => ({
    text: claim.text,
    evidence: claim.evidence_ids,
  });
  const newWarning = report.summary.find((c) => c.text.startsWith("Most frequent"));
  // How much of the log was errors: worded "N error events" before, "No errors, but ..." now.
  const scale = report.summary.find((c) => /error events|^No errors|\d+ errors \(/.test(c.text));
  const cause = report.suspected_cause[0];
  const quarantine = report.actions.find((a) => a.text.includes("quarantined"));
  const claims = [newWarning, scale, cause]
    .filter((c): c is NonNullable<typeof c> => c != null)
    .map(pick);
  if (quarantine) {
    claims.push({ text: quarantine.text, evidence: quarantine.evidence_ids });
  }

  const cited = new Set(claims.flatMap((c) => c.evidence));
  const replayEvidence: Record<string, ReplayEvidence> = {};
  for (const id of cited) {
    const e = evidence[id];
    if (!e) continue;
    replayEvidence[id] = {
      id,
      kind: e.kind,
      title: e.title,
      detail: e.detail.length > 280 ? `${e.detail.slice(0, 277)}...` : e.detail,
      lines: linesFor(id),
    };
  }

  const sev = demo.severity;
  return {
    title: stripSeverity(report.title),
    system: "HDFS",
    severity: sev.severity as Severity,
    probabilities: sev.probabilities as Record<Severity, number>,
    predictionSet: sev.prediction_set as Severity[],
    setEmpty: sev.set_empty ?? false,
    decidedBy: sev.decided_by,
    needsReview: sev.needs_review,
    confidence: sev.confidence,
    windowMinutes: Math.round((demo.batch.features.duration_s / 60) * 10) / 10,
    lines: shown,
    hiddenBefore: start - 1,
    claims,
    evidence: replayEvidence,
    nLines: demo.input.n_lines,
    timeToReviewMs: demo.timings.time_to_review_ms,
    recordedAt: demo.recorded_at,
    gitSha: demo.git_sha,
  };
}

/** Facts about each graph step of the recorded run, for the "how a run works" section. */
export function runFacts() {
  const batch = demo.batch;
  const guard = batch.guard;
  const inv = demo.investigation;
  const leading = inv?.hypotheses.find((h) => h.id === inv.leading_hypothesis);
  const tools = inv?.tool_calls ?? [];
  const report = demo.report;
  const ms = demo.timings.stage_ms as Record<string, number>;
  return {
    lines: demo.input.n_lines,
    shards: batch.shards,
    templates: batch.templates.length,
    pseudonyms: guard.redactions.pseudonyms,
    redactions: Object.values(guard.redactions.counts).reduce((a, b) => a + b, 0),
    quarantined: guard.injections.length,
    severity: demo.severity.severity,
    probability: demo.severity.probabilities[demo.severity.severity as Severity] ?? 0,
    similar: demo.retrieval?.incidents.length ?? 0,
    toolCalls: tools.length,
    toolNames: [...new Set(tools.map((t) => t.tool))],
    leadingConfidence: leading?.confidence ?? null,
    replans: demo.plan?.replans ?? 0,
    claims: report.validation.checked_claims,
    citationCoverage: report.validation.citation_coverage,
    actions: demo.actions.length,
    timeToReviewMs: demo.timings.time_to_review_ms,
    stageMs: ms,
  };
}

export type RunFacts = ReturnType<typeof runFacts>;

// --- evaluation --------------------------------------------------------------------------------

const METHOD_LABELS: Record<string, string> = {
  aria_policy: "ARIA (rules, model, floors, review)",
  model_only: "Calibrated model alone",
  model_with_floors: "Model with safety floors",
  tfidf_logreg: "TF-IDF + logistic regression",
  rules_only: "Rules alone",
  keyword: "Keyword matching",
  majority_class: "Always the most common class",
};

export interface MethodScore {
  key: string;
  label: string;
  accuracy: number;
  low: number;
  high: number;
  macroF1: number;
  severeUnderTriage: number;
}

// How a provider key reads in prose; offline providers never count as a live answer.
const PROVIDER_NAMES: Record<string, string> = {
  gemini: "Google Gemini",
  "gemini-lite": "Google Gemini",
  nim: "NVIDIA NIM",
  "nim-fallback": "NVIDIA NIM",
  "nim-local": "a self-hosted NIM",
  claude: "Anthropic Claude",
  openai: "OpenAI",
  azure: "Azure OpenAI",
  openai_compat: "an OpenAI-compatible endpoint",
};

const listFormat = new Intl.ListFormat("en-GB", { type: "conjunction" });

type LiveProvider = { calls: number; failures: number; models: string[] };

/** The hosted providers that answered at least one call, in the order the run tried them. */
function answered(providers: Record<string, LiveProvider>) {
  const live = Object.entries(providers).filter(
    ([name, p]) => name in PROVIDER_NAMES && p.calls > p.failures,
  );
  return {
    services: listFormat.format([...new Set(live.flatMap(([name]) => PROVIDER_NAMES[name] ?? []))]),
    models: [...new Set(live.flatMap(([, p]) => p.models))],
  };
}

export function evaluation() {
  const sev = evals.severity;
  const methods: MethodScore[] = Object.entries(sev.methods)
    .map(([key, m]) => ({
      key,
      label: METHOD_LABELS[key] ?? key,
      accuracy: m.accuracy,
      low: m.accuracy_ci95[0] ?? m.accuracy,
      high: m.accuracy_ci95[1] ?? m.accuracy,
      macroF1: m.macro_f1,
      severeUnderTriage: m.severe_under_triage,
    }))
    .sort((a, b) => b.accuracy - a.accuracy);
  const aria = sev.methods.aria_policy;
  const pipe = evals.pipeline;
  const livePipe = live.pipeline;
  const liveProviders = Object.entries(livePipe.providers).map(([name, p]) => ({
    name,
    models: p.models,
    calls: p.calls,
    failures: p.failures,
    p50s: p.latency_p50_ms / 1000,
    p95s: p.latency_p95_ms / 1000,
  }));
  return {
    createdAt: evals.created_at,
    gitSha: evals.git_sha,
    dataDescription: evals.data.description,
    severity: {
      n: sev.n,
      labels: sev.label_distribution,
      accuracy: aria.accuracy,
      ci: aria.accuracy_ci95,
      macroF1: aria.macro_f1,
      kappa: aria.quadratic_kappa,
      severeUnderTriage: aria.severe_under_triage,
      underTriage: aria.under_triage,
      overTriage: aria.over_triage,
      ece: sev.calibration.ece,
      brier: sev.calibration.brier,
      coverage: sev.conformal.coverage_raw,
      coverageWithFloors: sev.conformal.coverage_with_floors,
      targetCoverage: sev.conformal.target_coverage,
      setSize: sev.conformal.mean_set_size,
      autoDecided: sev.automation.auto_decided,
      decidedBy: sev.automation.decided_by as Record<string, number>,
      accuracyWhenAuto: sev.automation.accuracy_when_auto,
      accuracyWhenFlagged: sev.automation.accuracy_when_flagged,
      riskCoverage: sev.risk_coverage.points,
      aurc: sev.risk_coverage.aurc,
      methods,
      bySystem: sev.by_system,
      perClass: aria.per_class,
      confusion: aria.confusion,
    },
    pipeline: {
      n: pipe.n,
      valid: pipe.groundedness.valid_reports,
      cited: pipe.groundedness.every_claim_cited,
      recallAt3: pipe.retrieval.recall_at_3,
      mrr: pipe.retrieval.mrr,
      leadingCorrect: pipe.investigation.leading_hypothesis_correct,
      quietRuns: pipe.investigation.quiet_runs,
      falseAlarms: pipe.investigation.false_alarms,
      p50s: pipe.latency.time_to_review_p50_s,
      p95s: pipe.latency.time_to_review_p95_s,
      stageP50: pipe.latency.stage_p50_ms as Record<string, number>,
      stageP95: pipe.latency.stage_p95_ms as Record<string, number>,
      severityAccuracy: pipe.severity.accuracy,
      ndcg: pipe.retrieval.ndcg_at_3,
      recallAt1: pipe.retrieval.recall_at_1,
      incidentRuns: pipe.retrieval.n,
      meanToolCalls: pipe.budgets.mean_tool_calls,
    },
    robustness: {
      edgeN: evals.edge.n,
      attacks: evals.edge.attacks,
      benign: evals.edge.benign,
      parserErrors: evals.edge.parser_errors,
      attackRecall: evals.edge.attack_recall,
      byFamily: evals.edge.recall_by_family,
      benignFalsePositives: evals.edge.benign_false_positive_rate,
      windows: evals.robustness.n,
      severityInvariant: evals.robustness.severity_invariant,
      toolUseInvariant: evals.robustness.tool_use_invariant,
      reportsWithInjectedText: evals.robustness.reports_with_injected_text,
    },
    parsing: {
      systems: evals.parsing.n_systems,
      lines: evals.parsing.lines,
      meanAccuracy: evals.parsing.mean_grouping_accuracy,
      bySystem: evals.parsing.systems,
      gaia: {
        systems: evals.parsing.gaia.n_systems,
        lines: evals.parsing.gaia.lines,
        meanAccuracy: evals.parsing.gaia.mean_grouping_accuracy,
        knownAccuracy: evals.parsing.gaia.known.mean_grouping_accuracy,
        newAccuracy: evals.parsing.gaia.new.mean_grouping_accuracy,
        newSystems: evals.parsing.gaia.new.systems,
      },
    },
    live: {
      createdAt: live.created_at,
      n: livePipe.n,
      valid: livePipe.groundedness.valid_reports,
      cited: livePipe.groundedness.every_claim_cited,
      leadingCorrect: livePipe.investigation.leading_hypothesis_correct,
      incidentRuns: livePipe.retrieval.n,
      p50s: livePipe.latency.time_to_review_p50_s,
      p95s: livePipe.latency.time_to_review_p95_s,
      exhausted: livePipe.budgets.runs_with_exhausted_budget,
      maxTokens: livePipe.budgets.max_tokens_used,
      tokenLimit: livePipe.budgets.token_limit,
      stageP50: livePipe.latency.stage_p50_ms as Record<string, number>,
      latencyBudgetS: 180,
      writtenByModel: (livePipe.groundedness.written_by as Record<string, number>).llm ?? 0,
      answeredBy: answered(livePipe.providers).services || "no hosted provider",
      models: answered(livePipe.providers).models,
      providers: liveProviders,
    },
  };
}

export type Evaluation = ReturnType<typeof evaluation>;

/** The real-log evaluation (HDFS, expert labels), shaped for the landing and evaluation pages. */
export function realLogs() {
  const hdfs = evals.real.hdfs;
  const life = hdfs.lifecycle;
  const base = hdfs.baselines;
  const head = hdfs.contiguous;
  const detection = (d: typeof life) => ({
    precision: d.precision,
    precisionCi: d.precision_ci95,
    recall: d.recall,
    recallCi: d.recall_ci95,
    f1: d.f1,
    falseAlarms: d.fp,
    healthy: d.fp + d.tn,
    falseAlarmRate: d.false_alarm_rate,
    flagged: d.tp + d.fp,
  });
  return {
    fixture: hdfs.fixture,
    source: hdfs.source,
    citation: hdfs.citation,
    lines: hdfs.lines,
    minutes: hdfs.minutes,
    blocks: hdfs.blocks,
    failedBlocks: hdfs.anomalous_blocks,
    peakLinesPerMin: hdfs.peak_lines_per_min,
    judged: hdfs.judged,
    judgedFailed: hdfs.judged_anomalous,
    coverage: hdfs.coverage,
    recallAll: hdfs.recall_all,
    recallAllCi: hdfs.recall_all_ci95,
    windows: hdfs.replay.windows,
    windowMin: hdfs.replay.window_min,
    stepMin: hdfs.replay.step_min,
    minSupport: hdfs.replay.min_support,
    settleQuantile: hdfs.replay.settle_quantile,
    lifecycle: detection(life),
    engine: detection(base.engine_per_block),
    keyword: detection(base.keyword_per_block),
    // Standard unsupervised detectors on the same blocks, fitted on the whole sample at once.
    detectors: [
      {
        key: "rare",
        label: "Rare step counts (under 1% of blocks)",
        ...detection(base.rare_steps),
      },
      { key: "pairs", label: "Count pairs over the whole sample", ...detection(base.count_pairs) },
      { key: "forest", label: "Isolation forest", ...detection(base.isolation_forest) },
      { key: "pca", label: "PCA (Xu et al. 2009)", ...detection(base.pca) },
    ],
    steps: {
      distinct: hdfs.steps.distinct.failures,
      distinctCaught: hdfs.steps.distinct.caught,
      lookAlike: hdfs.steps.look_alike.failures,
      lookAlikeCaught: hdfs.steps.look_alike.caught,
      missed: hdfs.steps.missed.failures,
      missedPatterns: hdfs.steps.missed.patterns,
      missedTwinsMin: hdfs.steps.missed.healthy_twins_min,
    },
    head: head
      ? {
          lines: head.lines,
          minutes: head.minutes,
          judged: head.judged,
          flagged: head.tp + head.fp,
          falseAlarms: head.fp,
          precision: head.precision,
          recallAll: head.recall_all,
        }
      : null,
    windowLengths: hdfs.window_lengths,
    topPattern: hdfs.top_patterns[0] ?? null,
    patterns: hdfs.top_patterns,
    falseAlarmExamples: hdfs.false_alarms,
    sensitivity: hdfs.sensitivity,
    caughtBy: hdfs.caught_by as Record<string, number>,
  };
}

export type RealLogs = ReturnType<typeof realLogs>;

/** A detection rate with its exact interval, as the evaluation pages show it. */
interface Flagged {
  failed_flagged: number;
  failed: number;
  recall: number;
  recall_ci95: number[];
  normal_flagged: number;
  normal: number;
}

const flagged = (d: Flagged) => ({
  caught: d.failed_flagged,
  failed: d.failed,
  recall: d.recall,
  recallCi: d.recall_ci95,
  falseAlarms: d.normal_flagged,
  healthy: d.normal,
});

/** Part of a group flagged, with its exact interval. */
const share = (d: { flagged: number; of: number; share: number; ci95: number[] }) => ({
  caught: d.flagged,
  of: d.of,
  share: d.share,
  ci: d.ci95,
});

/** How well a score ranks failed runs above healthy ones: 0.5 is chance, 1 is perfect. */
const auroc = (d: { auroc: number; auroc_ci95: number[] }) => ({
  value: d.auroc,
  ci: d.auroc_ci95,
});

/**
 * The other real-data evaluations, each against labels its owners gave it: a supercomputer's
 * alert tags, a Hadoop cluster's injected failures, OpenStack runs with injected bugs, a service
 * desk's ticket outcomes, GitLab.com's incident labels, three clouds' post-mortems and public
 * prompt-injection benchmarks.
 * Every number comes from docs/eval-results.json.
 */
export function realData() {
  const {
    bgl,
    thunderbird,
    hadoop,
    openstack,
    uci_tickets: tickets,
    gitlab,
    postmortems,
    logchunks,
  } = evals.real;
  const errors = openstack.baselines.any_error_line;
  const injection = evals.injection_benchmarks;
  const retrieval = (m: (typeof gitlab.by.service.methods)["aria"]) => ({
    queries: m.queries,
    hit1: m.recall_at_1,
    hit3: m.recall_at_3,
    hit3Ci: m.recall_at_3_ci95,
    mrr: m.mrr_at_10,
  });
  const memory = (b: typeof gitlab.by.service) => ({
    labels: b.labels,
    labelled: b.memory_labelled,
    aria: retrieval(b.methods.aria),
    bm25: retrieval(b.methods.bm25),
    embeddings: retrieval(b.methods.embeddings),
    random: retrieval(b.methods.random),
    commonest: retrieval(b.methods.commonest_label),
  });
  // Thunderbird's labels hold no SEV1 or SEV2, so recall is keyed by the levels each log has.
  const severity = (
    m: Omit<(typeof bgl.methods)["aria_policy"], "recall"> & { recall: Record<string, number> },
  ) => ({
    accuracy: m.accuracy,
    accuracyCi: m.accuracy_ci95,
    macroF1: m.macro_f1,
    severeMissed: m.severe_missed,
    quietPaged: m.quiet_paged,
    recall: m.recall as Record<string, number>,
  });
  const labels = bgl.labels as Record<string, number>;
  const priority = (m: (typeof tickets.priority)["aria"]) => ({
    accuracy: m.accuracy,
    accuracyCi: m.accuracy_ci95,
    macroF1: m.macro_f1,
    severeMissed: m.severe_missed,
  });
  const byPriority = tickets.test_by_priority as Record<string, number>;
  const sources = injection.by_source as Record<
    string,
    { n: number; flagged: number; rate: number; ci95: number[] }
  >;
  const realLines = Object.values(
    injection.real_lines as Record<string, { n: number; flagged: number }>,
  );
  return {
    bgl: {
      citation: bgl.citation,
      lines: bgl.lines,
      days: bgl.days,
      alertLines: bgl.alert_lines,
      windows: bgl.windows,
      windowMin: bgl.window_min,
      labels,
      severe: (labels.SEV1 ?? 0) + (labels.SEV2 ?? 0),
      quiet: labels.SEV4 ?? 0,
      aria: severity(bgl.methods.aria_policy),
      rules: severity(bgl.methods.rules_only),
      model: severity(bgl.methods.model_only),
      keyword: severity(bgl.methods.keyword),
      highestLevel: severity(bgl.methods.highest_level),
      majority: severity(bgl.methods.majority_class),
      coverage: bgl.conformal.coverage,
      targetCoverage: bgl.conformal.target_coverage,
      autoDecided: bgl.automation.auto_decided,
      overlapShare: bgl.overlap_with_training_sample.share,
    },
    thunderbird: {
      citation: thunderbird.citation,
      lines: thunderbird.lines,
      days: thunderbird.days,
      alertLines: thunderbird.alert_lines,
      windows: thunderbird.windows,
      windowMin: thunderbird.window_min,
      labels: thunderbird.labels as Record<string, number>,
      quiet: (thunderbird.labels as Record<string, number>).SEV4 ?? 0,
      aria: severity(thunderbird.methods.aria_policy),
      rules: severity(thunderbird.methods.rules_only),
      keyword: severity(thunderbird.methods.keyword),
      majority: severity(thunderbird.methods.majority_class),
      coverage: thunderbird.conformal.coverage,
      targetCoverage: thunderbird.conformal.target_coverage,
      autoDecided: thunderbird.automation.auto_decided,
      /** The rules that fired most often on the quiet windows ARIA paged on, with their counts. */
      pagedBy: thunderbird.rules_on_paged_quiet_windows as [string, number][],
    },
    builds: {
      citation: logchunks.citation,
      builds: logchunks.triaged,
      languages: logchunks.languages,
      medianLines: logchunks.median_lines,
      meanKept: logchunks.mean_kept,
      aria: logchunks.aria,
      lastErrorLines: logchunks.baselines.last_error_lines,
      lastLines: logchunks.baselines.last_lines,
      randomLines: logchunks.baselines.random_lines,
    },
    hadoop: {
      citation: hadoop.citation,
      jobs: hadoop.jobs,
      lines: hadoop.lines,
      byLabel: hadoop.by_label as Record<string, number>,
      aria: flagged(hadoop.aria),
      anyError: flagged(hadoop.baselines.any_error_line),
      keyword: flagged(hadoop.baselines.keyword),
      severityByLabel: hadoop.severity_by_label as Record<string, Record<string, number>>,
      leadingByLabel: hadoop.leading_mode_by_label as Record<string, Record<string, number>>,
    },
    openstack: {
      citation: openstack.citation,
      experiments: openstack.experiments,
      lines: openstack.lines,
      bySubsystem: openstack.by_subsystem as Record<string, number>,
      failed: openstack.failed,
      reported: openstack.reported,
      silent: openstack.silent,
      aria: flagged(openstack.aria),
      paged: flagged(openstack.aria.paged),
      rules: flagged(openstack.baselines.rules_only),
      anyError: flagged(errors),
      keyword: flagged(openstack.baselines.keyword),
      ariaReported: share(openstack.aria.reported),
      ariaSilent: share(openstack.aria.silent),
      errorReported: share(errors.reported),
      errorSilent: share(errors.silent),
      unsure: openstack.review.failed.flagged + openstack.review.healthy.flagged,
      ranking: {
        aria: auroc(openstack.aria.ranking.all),
        ariaSilent: auroc(openstack.aria.ranking.silent),
        errors: auroc(errors.ranking.all),
        errorsSilent: auroc(errors.ranking.silent),
      },
    },
    tickets: {
      citation: tickets.citation,
      incidents: tickets.incidents,
      test: tickets.test,
      severe: (byPriority["1"] ?? 0) + (byPriority["2"] ?? 0),
      sameAsAtOpen: tickets.same_as_at_open,
      aria: priority(tickets.priority.aria),
      modelOnly: priority(tickets.priority.model_only),
      atOpen: priority(tickets.priority.priority_at_open),
      majority: priority(tickets.priority.majority_class),
      escalated: tickets.escalated.tickets,
      foreseen: tickets.escalated.foreseen,
      coverage: tickets.conformal.coverage,
      sla: {
        n: tickets.sla.n,
        breachRate: tickets.sla.breach_rate,
        auroc: tickets.sla.auroc,
        aurocCi: tickets.sla.auroc_ci95,
        baselines: tickets.sla.baselines_auroc as Record<string, number>,
        bestBaseline: Math.max(
          ...Object.values(tickets.sla.baselines_auroc as Record<string, number>),
        ),
      },
    },
    gitlab: {
      citation: gitlab.citation,
      incidents: gitlab.incidents,
      memory: gitlab.memory,
      later: gitlab.later,
      cutoff: gitlab.cutoff,
      top: gitlab.top,
      snapshot: gitlab.snapshot.downloaded_at.slice(0, 10),
      service: memory(gitlab.by.service),
      cause: memory(gitlab.by.cause),
    },
    postmortems: {
      citation: postmortems.citation,
      postmortems: postmortems.postmortems,
      byCloud: postmortems.by_cloud as Record<string, number>,
      memory: postmortems.memory,
      later: postmortems.later,
      cutoff: postmortems.cutoff,
      top: postmortems.top,
      fixLabelsSorted: postmortems.fix_labels_sorted,
      cause: memory(postmortems.by.cause),
      fix: memory(postmortems.by.fix),
    },
    injection: {
      attacks: injection.attacks.n,
      caught: injection.attacks.flagged,
      rate: injection.attacks.rate,
      rateCi: injection.attacks.ci95,
      sources: Object.entries(sources).map(([key, r]) => ({ key, ...r })),
      benign: {
        n: injection.benign.n,
        flagged: injection.benign.flagged,
        rate: injection.benign.rate,
      },
      realLines: realLines.reduce((total, r) => total + r.n, 0),
      realFlagged: realLines.reduce((total, r) => total + r.flagged, 0),
    },
  };
}

export type RealData = ReturnType<typeof realData>;
