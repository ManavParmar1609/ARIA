// Types for the ARIA API. Response bodies come from the OpenAPI schema (schema.ts, generated);
// graph state is untyped JSON on the wire, so its shape is written out here to mirror the
// Python contracts in src/aria/contracts (parsing.py, severity.py, retrieval.py, report.py,
// run.py). Keep the two in step when a contract changes.
import type { components } from "./schema";

type Schemas = components["schemas"];

export type RunSummary = Schemas["RunSummary"];
export type RunDetail = Schemas["RunDetail"];
export type RunPage = Schemas["RunPage"];
export type RunAccepted = Schemas["RunAccepted"];
export type RunEvent = Schemas["RunEvent"];
export type RunStatus = Schemas["RunStatus"];
export type Checkpoint = Schemas["Checkpoint"];
export type ReportOut = Schemas["ReportOut"];
export type IncidentReport = Schemas["IncidentReport"];
export type Claim = Schemas["Claim"];
export type Evidence = Schemas["Evidence"];
export type EvidenceKind = Schemas["EvidenceKind"];
export type SimilarIncident = Schemas["SimilarIncident"];
export type TimelineEntry = Schemas["TimelineEntry"];
export type ActionItem = Schemas["ActionItem"];
export type ValidationResult = Schemas["ValidationResult"];
export type TriageRequest = Schemas["TriageRequest"];
export type RunOptions = Schemas["RunOptions"];
export type ReviewRequest = Schemas["ReviewRequest"];
export type ReportEdits = Schemas["ReportEdits"];
export type ForkRequest = Schemas["ForkRequest"];
export type AskRequest = Schemas["AskRequest"];
export type AskResponse = Schemas["AskResponse"];
export type ClaimOut = Schemas["ClaimOut"];
export type IncidentOut = Schemas["IncidentOut"];
export type RunbookOut = Schemas["RunbookOut"];
export type RunbookStep = Schemas["RunbookStep"];
export type ProviderOut = Schemas["ProviderOut"];
export type Health = Schemas["Health"];

export type Severity = "SEV1" | "SEV2" | "SEV3" | "SEV4";
export const SEVERITIES: readonly Severity[] = ["SEV1", "SEV2", "SEV3", "SEV4"];

export const SEVERITY_MEANING: Record<Severity, string> = {
  SEV1: "Critical: widespread outage or data-loss risk. Page now.",
  SEV2: "High: major degradation or a failing critical component.",
  SEV3: "Moderate: contained errors with limited user impact.",
  SEV4: "Low: informational or noise. No action needed now.",
};

export function isSeverity(value: unknown): value is Severity {
  return typeof value === "string" && (SEVERITIES as readonly string[]).includes(value);
}

// --- graph state (GET /api/v1/runs/{id}/state) -------------------------------------------------

export type DecidedBy = "rules" | "model" | "llm" | "fallback" | "human";

export interface RuleHit {
  rule_id: string;
  title: string;
  effect: "score" | "floor";
  severity: Severity;
  weight: number;
  detail: string;
  evidence_ids: string[];
}

export interface SeverityAssessment {
  severity: Severity;
  decided_by: DecidedBy;
  rule_severity: Severity;
  rule_scores: Partial<Record<Severity, number>>;
  rule_hits: RuleHit[];
  probabilities: Partial<Record<Severity, number>>;
  prediction_set: Severity[];
  /** No class cleared the conformal threshold; the set holds the most likely class as a stand-in. */
  set_empty?: boolean;
  alpha: number;
  floor: Severity | null;
  confidence: number;
  auditable: boolean;
  needs_review: boolean;
  rationale: Claim[];
  model_version: string;
}

export interface LogEvent {
  idx: number;
  line_no: number | null;
  ts: string | null;
  node: string | null;
  component: string | null;
  level: string | null;
  message: string;
  template_id: string;
  flags: string[];
}

export interface TemplateStat {
  template_id: string;
  template: string;
  count: number;
  levels: Record<string, number>;
  nodes: number;
  first_ts: string | null;
  last_ts: string | null;
  error_like: boolean;
  novel: boolean;
  components: string[];
  sample_idx: number[];
  evidence_id: string;
}

export interface WindowFeatures {
  n_events: number;
  n_templates: number;
  duration_s: number;
  events_per_min: number;
  level_counts: Record<string, number>;
  error_events: number;
  error_ratio: number;
  keyword_hits: Record<string, number>;
  burst_score: number;
  peak_errors_per_min: number;
  distinct_nodes: number;
  error_nodes: number;
  node_spread: number;
  novel_templates: number;
  novel_error_templates: number;
  warn_nodes: number;
  peak_warnings_per_min: number;
  novel_warn_templates: number;
  components: string[];
  critical_components: string[];
  max_component_criticality: number;
  persistence_s: number;
  flows_checked?: number;
  broken_flows?: number;
  broken_flow_ratio?: number;
}

export interface InjectionFinding {
  line_idx: number;
  pattern: string;
  excerpt: string;
  score: number;
}

export interface GuardReport {
  redactions: { counts: Record<string, number>; pseudonyms: number };
  injections: InjectionFinding[];
  safety: { provider: string; safe: boolean; categories: string[] } | null;
  truncated_lines: number;
  dropped_lines: number;
}

/** A unit of work (an HDFS block, a task attempt) that broke off partway or took a rare step. */
export interface BrokenUnit {
  kind: string;
  key: string;
  problem: "mismatch" | "unusual_step";
  reason: string;
  steps: string[];
  first_ts: string | null;
  last_ts: string | null;
  lines: number[];
  evidence_id: string | null;
}

/** Units of work the parser followed from start to finish. */
export interface FlowCheck {
  units: Record<string, number>;
  checked: Record<string, number>;
  broken: number;
  settle_s: Record<string, number>;
  pairs: { kind: string; steps: string[]; units: number; support: number }[];
  examples: BrokenUnit[];
  broken_keys: string[];
  evidence_id: string | null;
}

export interface ParsedBatch {
  system: string;
  n_raw_lines: number;
  events: LogEvent[];
  templates: TemplateStat[];
  features: WindowFeatures;
  guard: GuardReport;
  shards: number;
  template_history: number;
  flows?: FlowCheck;
}

export interface ToolCallRecord {
  call_id: string;
  agent: string;
  tool: string;
  arguments: Record<string, unknown>;
  ok: boolean;
  summary: string;
  evidence_ids: string[];
  duration_ms: number;
}

export interface Hypothesis {
  id: string;
  statement: string;
  failure_mode: string;
  component: string | null;
  status: "open" | "supported" | "refuted" | "inconclusive";
  confidence: number;
  supporting: string[];
  refuting: string[];
}

export interface Investigation {
  hypotheses: Hypothesis[];
  steps: number;
  tool_calls: ToolCallRecord[];
  leading_hypothesis: string | null;
  summary: Claim[];
  stopped_reason: string;
}

export interface RetrievalAttempt {
  attempt: number;
  query: string;
  filters: Record<string, string>;
  candidates: number;
  grade: number;
  widened: boolean;
}

export interface RunbookRef {
  slug: string;
  title: string;
  failure_modes: string[];
  steps: string[];
  risk: "low" | "medium" | "high";
  evidence_id: string | null;
}

export interface RetrievalResult {
  incidents: SimilarIncident[];
  runbooks: RunbookRef[];
  attempts: RetrievalAttempt[];
  grade: number;
  reranked: boolean;
}

export interface OutboundAction {
  action_id: string;
  kind: "slack" | "teams" | "webhook" | "status_page" | "ticket_draft";
  audience: "responders" | "stakeholders" | "customers";
  title: string;
  body: string;
  status: "proposed" | "approved" | "rejected" | "sent" | "failed" | "skipped";
  requires_approval: boolean;
  evidence_ids: string[];
}

export interface Plan {
  investigate: boolean;
  use_llm: boolean;
  fanout_shards: number;
  retrieval_k: number;
  retrieval_candidates: number;
  widen_level: number;
  context_lines: number;
  validation: "standard" | "strict";
  replans: number;
  max_replans: number;
  notes: string[];
}

export interface BudgetUsage {
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  cost_known: boolean;
  llm_calls: number;
  tool_calls: number;
  steps: number;
  started_at: string;
  exhausted: string[];
}

export interface RunStateValues {
  run_id?: string;
  status?: string;
  request?: Record<string, unknown>;
  plan?: Plan;
  batch?: ParsedBatch;
  severity?: SeverityAssessment;
  retrieval?: RetrievalResult;
  investigation?: Investigation;
  replan_reasons?: string[];
  report?: IncidentReport;
  report_meta?: Record<string, unknown>;
  actions?: OutboundAction[];
  review?: { decision: string; reviewer: string; comment?: string | null };
  evidence?: Evidence[];
  budget?: BudgetUsage;
  notes?: string[];
  errors?: Record<string, unknown>[];
}

export interface RunState {
  values: RunStateValues;
  next: string[];
  checkpoint_id: string | null;
}

/** The review interrupt a run pauses on (RunDetail.review while awaiting review). */
export interface ReviewPrompt {
  type: "review";
  run_id: string;
  report_id: string;
  title: string;
  severity: Severity;
  decided_by: DecidedBy;
  confidence: number;
  needs_review: boolean;
  prediction_set: Severity[];
  valid: boolean;
  generated_by: "template" | "llm";
  actions: Pick<OutboundAction, "action_id" | "kind" | "audience" | "title">[];
  decisions: ("approve" | "edit" | "reject")[];
  error?: string | null;
}
