// Everything the video shows comes from two committed files: one recorded ARIA run
// (scripts/record_demo_run.py writes web/src/data/demo-run.json) and the offline evaluation
// (`make eval` writes docs/eval-results.json). Nothing here is typed in by hand.
import demo from "../../web/src/data/demo-run.json";
import evals from "../../docs/eval-results.json";

import type { Severity } from "./theme";

const SEVERITIES: Severity[] = ["SEV1", "SEV2", "SEV3", "SEV4"];

const minutes = (seconds: number) => `${(seconds / 60).toFixed(1)} minutes`;

const short = (text: string, max: number) =>
  text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`;

const clock = (iso: string | null) => (iso ? iso.slice(11, 19) : "--:--:--");

const pct = (value: number, digits = 1) => `${(100 * value).toFixed(digits)}%`;

// --- the recorded run --------------------------------------------------------------------------

const batch = demo.batch;
const severity = demo.severity;
// The window around the line the parser flagged as a prompt-injection attempt.
const plantedAt = batch.events.findIndex((e) => e.flags.includes("injection_suspect"));
const around = batch.events.slice(Math.max(0, plantedAt - 5), plantedAt + 4);

export const run = {
  title: demo.source.title,
  system: "HDFS",
  synthetic: demo.source.synthetic,
  lines: demo.input.n_lines,
  span: minutes(batch.features.duration_s),
  // The lines the well shows, as the parser kept them (redacted), around the planted one.
  well: around.map((e) => ({
    time: clock(e.ts),
    level: e.level ?? "",
    text: short(`${e.component ?? ""}: ${e.message}`, 66),
    planted: e.flags.includes("injection_suspect"),
  })),
  events: batch.features.n_events,
  templates: batch.templates.slice(0, 5).map((t) => ({
    text: short(t.template, 58),
    count: t.count,
    novel: t.novel,
  })),
  nTemplates: batch.templates.length,
  ips: batch.guard.redactions.counts.ip,
  pseudonyms: batch.guard.redactions.pseudonyms,
  quarantined: batch.guard.injections.length,
};

export const assessment = {
  severity: severity.severity as Severity,
  rule: severity.rule_severity as Severity,
  hits: severity.rule_hits.map((h) => ({ title: h.title, severity: h.severity as Severity })),
  probabilities: SEVERITIES.map((s) => ({
    severity: s,
    p: severity.probabilities[s],
  })),
  set: severity.prediction_set as Severity[],
  coverage: pct(1 - severity.alpha, 0),
  confidence: severity.confidence,
  decidedBy: severity.decided_by,
};

const investigation = demo.investigation;
export const investigate = {
  tools: investigation.tool_calls.map((t) => t.tool),
  hypotheses: investigation.hypotheses.map((h) => ({
    name: h.failure_mode.replaceAll("_", " "),
    status: h.status,
    confidence: h.confidence,
  })),
  incidents: demo.retrieval.incidents.slice(0, 3).map((i) => ({
    title: i.title,
    severity: i.severity as Severity,
    seen: i.occurrences,
  })),
  runbook: demo.retrieval.runbooks[0]?.slug ?? "",
};

const report = demo.report;
const evidence = new Map(report.evidence.map((e) => [e.id, e]));
export const cited = {
  title: report.title.replace(/^SEV\d · /, ""),
  severity: report.severity as Severity,
  claims: [...report.summary, ...report.suspected_cause].map((c) => ({
    text: c.text,
    ids: c.evidence_ids,
  })),
  checked: report.validation.checked_claims,
  coverage: pct(report.validation.citation_coverage, 0),
  // The evidence behind the claim about the new warning template.
  focus: (() => {
    const e = evidence.get("E2");
    return e
      ? { id: e.id, kind: e.kind.replaceAll("_", " "), title: e.title, detail: e.detail }
      : null;
  })(),
};

export const review = {
  actions: demo.actions.map((a) => ({ kind: a.kind, title: a.title })),
  timeToReview: `${demo.timings.time_to_review_ms} ms`,
  status: demo.status,
};

// --- the measured results ------------------------------------------------------------------------

const methods = evals.severity.methods;
export const measured = {
  commit: evals.git_sha,
  windows: evals.severity.n,
  accuracy: pct(methods.aria_policy.accuracy),
  tfidf: pct(methods.tfidf_logreg.accuracy),
  rules: pct(methods.rules_only.accuracy),
  runs: evals.pipeline.n,
  cited: pct(evals.pipeline.groundedness.every_claim_cited, 0),
  attacks: evals.edge.attacks.toLocaleString("en-US"),
  benign: evals.edge.benign.toLocaleString("en-US"),
  quarantined: pct(evals.edge.attack_recall),
  falsePositives: pct(evals.edge.benign_false_positive_rate),
};

// Real HDFS logs with the experts' labels (docs/evaluation.md, "Real logs").
const hdfs = evals.real.hdfs;
export const realLogs = {
  precision: pct(hdfs.lifecycle.precision),
  recall: pct(hdfs.lifecycle.recall),
  recallAll: pct(hdfs.recall_all),
};

export const REPO = "github.com/ManavParmar1609/ARIA";
