import type { Evidence } from "@/lib/api/types";
import { plainTemplate } from "@/lib/format";
import { systemName } from "@/lib/systems";

// Evidence as a person reads it: titles, details and the severity model's measurements in words.
// Pure text, so the landing page's replay can use it without the evidence panel.

/**
 * An evidence title as a person reads it. A pattern is recorded as "16x Failed password for
 * <*> port <*>"; it reads "16 lines like “Failed password for … port …”".
 */
export function evidenceTitle(evidence: { kind: string; title: string }): string {
  if (evidence.kind === "incident") return incidentTitle(evidence.title);
  if (evidence.kind === "rule") return ruleTitle(evidence.title);
  if (evidence.kind === "model") return modelTitle(evidence.title);
  if (evidence.kind === "feature") return featureTitle(evidence.title);
  const pattern = evidence.kind === "template" ? /^(\d+)x (.+)$/s.exec(evidence.title) : null;
  if (!pattern?.[1] || !pattern[2]) return evidence.title;
  const n = Number(pattern[1]);
  const text = plainTemplate(pattern[2]);
  return n === 1 ? `1 line: “${text}”` : `${n.toLocaleString("en")} lines like “${text}”`;
}

// "158 events, 12 errors (7.6%) over 9.7 min", as the parser measures a window.
const FEATURE_TITLE = /^(\d+) events, (\d+) errors \(([\d.]+%)\) over ([\d.]+) min$/;

/** A window's size in words: "158 lines, 12 errors (7.6%), over 9.7 minutes". */
function featureTitle(title: string): string {
  const found = FEATURE_TITLE.exec(title);
  if (!found) return title;
  const [, lines, errors, share, minutes] = found;
  const many = lines === "1" ? "1 line" : `${Number(lines).toLocaleString("en")} lines`;
  const bad =
    errors === "0"
      ? "no errors"
      : `${Number(errors).toLocaleString("en")} ${errors === "1" ? "error" : "errors"} (${share})`;
  return `${many}, ${bad}, over ${minutes} minutes`;
}

// "Similar incident syn-x-1: Disk filling up (SEV3; 6x on hdfs)", as the retriever records it.
const INCIDENT_TITLE = /^Similar incident \S+: (.+) \((SEV\d); (\d+)x on (\S+)\)$/s;

/** A past incident's evidence title without its record id: "Disk filling up: SEV3, seen 6 times
 * on HDFS". */
function incidentTitle(title: string): string {
  const found = INCIDENT_TITLE.exec(title);
  if (!found) return title;
  const [, name, severity, times, system] = found;
  const seen = times === "1" ? "seen once" : `seen ${times} times`;
  return `${name}: ${severity}, ${seen} on ${systemName(system)}`;
}

// "Rule crash_widespread (floor SEV2): Crashes on several servers", as the rules record it.
const RULE_TITLE = /^Rule \S+ \((score|floor) (SEV\d)\): (.+)$/s;

/** A rule's evidence title without its id: "Crashes on several servers (safety floor: SEV2)". */
function ruleTitle(title: string): string {
  const found = RULE_TITLE.exec(title);
  if (!found) return title;
  const [, effect, severity, what] = found;
  return `${what} (${effect === "floor" ? "safety floor:" : "counts toward"} ${severity})`;
}

// "Severity probabilities: SEV1 0.03, SEV2 0.11, ...", as the severity model records it; without
// the model, "Rule-score probabilities: ..." are the rule scores shared out across the levels.
const MODEL_TITLE = /^(Severity|Rule-score) probabilities: (.+)$/s;

/** The severity model's evidence title in percentages: "How likely each level is: SEV1 3%, ...". */
function modelTitle(title: string): string {
  const found = MODEL_TITLE.exec(title);
  if (!found?.[2]) return title;
  const levels = found[2].replace(
    /(SEV\d) (\d(?:\.\d+)?)/g,
    (_, level: string, p: string) => `${level} ${chance(Number(p))}`,
  );
  return found[1] === "Severity"
    ? `How likely each level is: ${levels}`
    : `Each level's share of the rule scores: ${levels}`;
}

/** A probability as a person reads it: "54%", and "under 1%" rather than a bare "0%". */
export function chance(p: number): string {
  if (p > 0 && p < 0.005) return "under 1%";
  if (p < 1 && p >= 0.995) return "over 99%";
  return `${Math.round(p * 100)}%`;
}

/** Evidence detail as a person reads it. A past incident's record names its runbook by file
 * ("Followed runbook hdfs-block-serve: ..."), and a sample-built one counts "0 error events on 0
 * of 0 nodes": both read as the steps, and as no errors, instead. */
export function evidenceDetail(evidence: Pick<Evidence, "kind" | "detail">): string {
  const detail = evidence.detail ?? "";
  if (evidence.kind !== "incident") return detail;
  return detail
    .split("\n")
    .map((line) =>
      line
        .replace(/^Resolution: Followed runbook \S+: /, "Resolution: ")
        .replace(
          /^Summary: 0 error events on 0 of \d+ nodes over (\d+) min \(peak 0\/min\)\.?$/,
          "Summary: no error lines over $1 minutes.",
        )
        .replace(
          / nodes over (\d+) min \(peak (\d+)\/min\)/,
          " servers over $1 minutes (at most $2 a minute)",
        ),
    )
    .join("\n");
}

// The severity model's measurements as the report would name them, with "log1p.", "frac." and
// "keyword_hits." prefixes read away.
const FEATURE_NAMES: Record<string, string> = {
  n_events: "lines",
  error_events: "error lines",
  events_per_min: "lines a minute",
  peak_errors_per_min: "errors a minute at the peak",
  distinct_nodes: "servers",
  error_nodes: "servers with errors",
  n_templates: "patterns",
  novel_templates: "new patterns",
  novel_error_templates: "new error patterns",
  peak_warnings_per_min: "warnings a minute at the peak",
  warn_nodes: "servers with warnings",
  novel_warn_templates: "new warning patterns",
  n_critical_components: "critical services",
  "alerts.firing": "alerts firing",
  "alerts.critical": "critical alerts",
  "alerts.warning": "warning alerts",
  error_ratio: "share of error lines",
  node_spread: "spread across servers",
  max_component_criticality: "most critical service",
  burst_score: "error burst",
  persistence_min_log1p: "how long errors lasted",
  floor_rank: "safety floor",
};
const KEYWORD_TOPICS: Record<string, string> = {
  crash: "crashes",
  data_risk: "data loss",
  unavailable: "outages",
  resource: "running out of resources",
  degradation: "slowness",
  network: "the network",
};

/** A severity-model measurement in words: "log1p.keyword_hits.crash" reads "words about crashes". */
export function featureName(name: string): string {
  const bare = name.replace(/^log1p\./, "");
  const keyword = /^keyword_hits\.(\w+)$/.exec(bare)?.[1];
  if (keyword) return `words about ${KEYWORD_TOPICS[keyword] ?? keyword.replaceAll("_", " ")}`;
  const level = /^frac\.(\w+)$/.exec(bare)?.[1];
  if (level) return `share of ${level} lines`;
  const rule = /^rule_p\.(SEV\d)$/.exec(bare)?.[1];
  if (rule) return `rules' score for ${rule}`;
  return FEATURE_NAMES[bare] ?? bare.replaceAll("_", " ");
}
