import type { Evidence } from "@/lib/api/types";
import { failureName } from "@/lib/failure-modes";
import { plainTemplate } from "@/lib/format";
import { systemName } from "@/lib/systems";

// Evidence as a person reads it: titles, details and the severity model's measurements in words.
// Pure text, so the landing page's replay can use it without the evidence panel.

/**
 * An evidence title as a person reads it. A pattern is recorded as "16x Failed password for
 * <*> port <*>"; it reads "16 lines like “Failed password for … port …”".
 */
export function evidenceTitle(evidence: {
  kind: string;
  title: string;
  data?: Record<string, unknown> | null;
}): string {
  if (evidence.kind === "incident") return incidentTitle(evidence.title);
  if (evidence.kind === "rule") return ruleTitle(evidence.title);
  if (evidence.kind === "model") return modelTitle(evidence.title);
  if (evidence.kind === "feature") return featureTitle(evidence.title);
  if (evidence.kind === "tool") return toolTitle(evidence.title, evidence.data);
  if (evidence.kind === "hypothesis") return causeTitle(evidence.title, evidence.data);
  if (evidence.kind === "runbook") return evidence.title.replace(/^Runbook \S+: /, "Runbook: ");
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

// What ARIA did with each of its read-only tools.
const TOOL_DID: Record<string, string> = {
  search_incidents: "Searched past incidents",
  get_incident: "Read a past incident",
  summarize_incident: "Read a past incident's summary",
  search_runbooks: "Searched the runbooks",
  get_runbook: "Read a runbook",
  get_ticket_history: "Read the ticket history",
  search_logs: "Searched the logs",
  get_template_examples: "Looked up example lines",
  component_timeline: "Read a component's timeline",
  node_breakdown: "Counted problems by server",
};

const count = (n: string, one: string, many: string) =>
  `${Number(n).toLocaleString("en")} ${n === "1" ? one : many}`;

/** The gist of a tool's one-line summary, as the tool belt writes it (mcp/client.py), without
 * record ids, file names or a cut-off payload. */
function toolGist(summary: string): string {
  let found: RegExpExecArray | null;
  if (summary === "no similar incidents") return "none similar";
  if ((found = /^(\d+) similar incidents\b/.exec(summary)) && found[1]) {
    return count(found[1], "similar incident", "similar incidents");
  }
  if ((found = /^(\d+) log lines( \(more not shown\))?/.exec(summary)) && found[1]) {
    return `${count(found[1], "line", "lines")}${found[2] ? ", and more not shown" : ""}`;
  }
  found = /^(.+): (\d+) lines over (\d+) min, (\d+) errors and (\d+) warnings/.exec(summary);
  if (found?.[1] && found[2] && found[3] && found[4] && found[5]) {
    return `${found[1]}, ${count(found[2], "line", "lines")} over ${count(found[3], "minute", "minutes")}: ${count(found[4], "error", "errors")} and ${count(found[5], "warning", "warnings")}`;
  }
  if ((found = /^no lines for component (.+)$/.exec(summary)) && found[1]) {
    return `no lines from ${found[1]}`;
  }
  if ((found = /^(\d+) nodes? with errors or warnings/.exec(summary)) && found[1]) {
    return `${count(found[1], "server", "servers")} with errors or warnings`;
  }
  if (summary === "no nodes") return "no servers";
  if ((found = /^runbooks: (.*)$/.exec(summary))) {
    const n = String(found[1] ? found[1].split(", ").length : 0);
    return count(n, "runbook", "runbooks");
  }
  found = /^runbook \S+: (\d+) mitigation steps \(risk (\w+)\)/.exec(summary);
  if (found?.[1] && found[2]) {
    return `${count(found[1], "step", "steps")} to fix it, ${found[2]} risk`;
  }
  if ((found = /^(\d+) similar tickets$/.exec(summary)) && found[1]) {
    return count(found[1], "similar ticket", "similar tickets");
  }
  if (summary === "no ticket history") return "no similar tickets";
  if (/ returned \d+ bytes$/.test(summary)) return "done";
  return shortened(summary, 120);
}

/** Text cut at a word boundary, with an ellipsis when anything was cut. */
function shortened(text: string, most: number): string {
  if (text.length <= most) return text;
  const cut = text.slice(0, most);
  const space = cut.lastIndexOf(" ");
  return `${(space > most / 2 ? cut.slice(0, space) : cut).replace(/[\s,;:]+$/, "")}…`;
}

/** A tool result's title: what ARIA did and what came back, "Searched past incidents for “got
 * exception while serving”: 3 similar incidents". */
function toolTitle(title: string, data?: Record<string, unknown> | null): string {
  const named = /^(\w+): /.exec(title)?.[1] ?? "";
  const tool = typeof data?.tool === "string" ? data.tool : named;
  const summary = named === tool ? title.slice(tool.length + 2) : title;
  const args = data?.arguments;
  const query =
    args && typeof args === "object" && "query" in args && typeof args.query === "string"
      ? args.query
      : null;
  const did = TOOL_DID[tool];
  if (!did) return title;
  return `${did}${query ? ` for “${shortened(query, 60)}”` : ""}: ${toolGist(summary)}`;
}

// Hypothesis statuses, as the investigator records them ("H1 supported: ...").
const CAUSE_STATUS: Record<string, string> = {
  supported: "Likely cause",
  refuted: "Ruled out",
  inconclusive: "Not settled",
  open: "Still open",
};

/** A cause the investigator tested, by what it found: "Likely cause, 93% sure: ...". */
function causeTitle(title: string, data?: Record<string, unknown> | null): string {
  const found = /^H\d+ (\w+): (.+)$/s.exec(title);
  if (!found?.[1] || !found[2]) return title;
  const status = CAUSE_STATUS[found[1]] ?? found[1];
  const sure =
    found[1] === "supported" && typeof data?.confidence === "number"
      ? `, ${chance(data.confidence)} sure`
      : "";
  return `${status}${sure}: ${found[2]}`;
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
  if (evidence.kind === "tool") return toolDetail(detail);
  if (evidence.kind === "runbook") return detail.replace(/ \[risk: (\w+)\]/g, " ($1 risk)");
  if (evidence.kind === "hypothesis") {
    const found = /^failure mode (\S+); component (.+)$/.exec(detail);
    return found?.[1] && found[2]
      ? `Kind of failure: ${failureName(found[1])}. Component: ${found[2]}.`
      : detail;
  }
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

const parsed = (detail: string): Record<string, unknown> | null => {
  try {
    const value: unknown = JSON.parse(detail);
    return value && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : null;
  } catch {
    return null; // a long result is stored cut short, so it may not parse
  }
};

const rows = (value: unknown): Record<string, unknown>[] =>
  Array.isArray(value)
    ? value.filter((v): v is Record<string, unknown> => Boolean(v) && typeof v === "object")
    : [];

const text = (value: unknown) => (typeof value === "string" ? value : String(value ?? ""));

/** What a tool sent back, in lines a person reads: the past incidents by title, the log lines, a
 * runbook's steps. The raw result stays one click away (see `rawResult`). */
function toolDetail(detail: string): string {
  const data = parsed(detail);
  if (!data) return "";
  if (Array.isArray(data.incidents)) {
    return rows(data.incidents)
      .slice(0, 5)
      .map((i) => {
        const seen = Number(i.occurrences);
        return `${text(i.title)} (${text(i.severity)}${seen > 1 ? `, seen ${seen} times` : ""})`;
      })
      .join("\n");
  }
  if (Array.isArray(data.lines)) {
    return rows(data.lines)
      .slice(0, 5)
      .map((l) => `line ${text(l.line_no)}: ${text(l.message)}`)
      .join("\n");
  }
  if (Array.isArray(data.mitigate)) {
    const steps = data.mitigate.map(
      (step, i) => `${i + 1}. ${text(step).replace(/ \[risk: (\w+)\]/g, " ($1 risk)")}`,
    );
    return [text(data.title), ...steps].filter(Boolean).join("\n");
  }
  if (Array.isArray(data.nodes)) {
    return rows(data.nodes)
      .slice(0, 5)
      .map(
        (n) =>
          `${text(n.node)}: ${count(text(n.errors), "error", "errors")}, ${count(text(n.warnings ?? 0), "warning", "warnings")}`,
      )
      .join("\n");
  }
  if (Array.isArray(data.runbooks)) {
    return rows(data.runbooks)
      .slice(0, 5)
      .map((r) => text(r.title ?? r.slug))
      .join("\n");
  }
  return "";
}

/** A tool's result as it came back, laid out to read, for whoever wants the record itself. */
export function rawResult(evidence: Pick<Evidence, "kind" | "detail">): string | null {
  if (evidence.kind !== "tool" || !evidence.detail) return null;
  const data = parsed(evidence.detail);
  return data ? JSON.stringify(data, null, 2) : evidence.detail;
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
