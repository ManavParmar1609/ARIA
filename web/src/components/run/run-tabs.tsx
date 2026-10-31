"use client";

import { useMemo, useState } from "react";

import { SeverityBadge } from "@/components/aria/severity";
import type { Evidence, GuardReport, ParsedBatch, RetrievalResult } from "@/lib/api/types";
import { isSeverity } from "@/lib/api/types";
import { percent } from "@/lib/format";
import { cn } from "@/lib/utils";

import { Citations, EvidenceChip, KIND_LABEL, useEvidence } from "./evidence";

/** All evidence the run collected, filterable by kind. */
// Where a past incident in memory came from, as the incident library names it.
const SOURCE: Record<string, string> = {
  curated: "built from a sample",
  run: "from an approved incident",
  memory: "from memory",
};

export function EvidenceTable({ evidence, cited }: { evidence: Evidence[]; cited: Set<string> }) {
  const [kind, setKind] = useState<string>("all");
  const { active, pin } = useEvidence();
  const kinds = useMemo(() => {
    const counts = new Map<string, number>();
    for (const e of evidence) counts.set(e.kind, (counts.get(e.kind) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [evidence]);
  const shown = kind === "all" ? evidence : evidence.filter((e) => e.kind === kind);
  return (
    <div className="grid gap-4">
      <div role="group" aria-label="Filter evidence by kind" className="flex flex-wrap gap-1.5">
        {[["all", evidence.length] as const, ...kinds].map(([k, n]) => (
          <button
            key={k}
            type="button"
            aria-pressed={kind === k}
            onClick={() => setKind(k)}
            className={cn(
              "h-7 rounded-md border px-2.5 text-xs",
              kind === k
                ? "border-primary bg-highlight text-highlight-foreground"
                : "border-rule text-muted-foreground hover:text-foreground",
            )}
          >
            {k === "all" ? "All" : (KIND_LABEL[k] ?? k)} <span className="tabular">{n}</span>
          </button>
        ))}
      </div>
      <ul className="grid gap-1.5">
        {shown.map((e) => (
          <li
            key={e.id}
            className={cn(
              "grid grid-cols-[3.75rem_1fr] items-baseline gap-3 rounded-sm px-2 py-1.5 text-sm",
              active === e.id && "bg-highlight",
            )}
          >
            <EvidenceChip id={e.id} />
            <button type="button" onClick={() => pin(e.id)} className="min-w-0 text-left">
              <span className="block truncate">{e.title}</span>
              <span className="block text-xs text-muted-foreground">
                {KIND_LABEL[e.kind] ?? e.kind}, from {e.source}
                {cited.has(e.id) ? ", cited in the report" : ""}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

// What each redaction counted, as people say it ("91 IP addresses", not "91 ip").
const REDACTED: Record<string, string> = {
  ip: "IP address",
  email: "email address",
  payment_card: "card number",
  assigned_secret: "secret setting",
  private_key: "private key line",
  jwt: "JWT",
  aws_access_key: "AWS access key",
  nvidia_key: "NVIDIA API key",
  openai_key: "OpenAI key",
  github_token: "GitHub token",
  gitlab_token: "GitLab token",
  slack_token: "Slack token",
  slack_webhook: "Slack webhook",
  google_api_key: "Google API key",
  stripe_key: "Stripe key",
  sendgrid_key: "SendGrid key",
  bearer_token: "bearer token",
  basic_auth: "Basic credential",
  url_credentials: "URL credential",
};

function redacted(kind: string, n: number): string {
  const name = REDACTED[kind] ?? kind.replaceAll("_", " ");
  const plural = n === 1 ? name : name.endsWith("address") ? `${name}es` : `${name}s`;
  return `${n.toLocaleString("en")} ${plural}`;
}

function Guard({ guard, raw }: { guard: GuardReport; raw: number }) {
  const redactions = Object.entries(guard.redactions?.counts ?? {});
  return (
    <div className="grid gap-3 rounded-lg bg-raised p-5 text-sm">
      <h3 className="font-sans font-semibold">Guardrails on the way in</h3>
      <p className="text-muted-foreground">
        {raw.toLocaleString("en")} lines read.{" "}
        {redactions.length
          ? `Redacted or pseudonymised: ${redactions.map(([k, n]) => redacted(k, n)).join(", ")}.`
          : "Nothing needed redacting."}{" "}
        {guard.truncated_lines ? `${guard.truncated_lines} over-long lines were truncated. ` : ""}
        {guard.dropped_lines ? `${guard.dropped_lines} lines beyond the limit were dropped.` : ""}
      </p>
      {guard.injections?.length ? (
        <div className="grid gap-2">
          <p className="font-medium text-sev3-fg">
            {guard.injections.length} line{guard.injections.length === 1 ? "" : "s"} quarantined as
            possible prompt injection, and kept out of the analysis:
          </p>
          <ul className="grid gap-1.5">
            {guard.injections.map((f) => (
              <li
                key={f.line_idx}
                className="rounded-sm border border-rule bg-sunken p-2 font-mono text-xs break-words"
              >
                <span className="text-faint">line {f.line_idx + 1}: </span>
                {f.excerpt.trim()}
                <span className="block pt-1 font-sans text-xs text-muted-foreground">
                  matched {f.pattern.replaceAll("+", ", ").replaceAll("_", " ")} (score{" "}
                  {f.score.toFixed(2)})
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {guard.safety ? (
        <p className="text-muted-foreground">
          Content-safety check by {guard.safety.provider}:{" "}
          {guard.safety.safe ? "safe" : `flagged (${guard.safety.categories.join(", ")})`}.
        </p>
      ) : null}
    </div>
  );
}

/** What the parser made of the logs: templates by weight, and what the guard caught. */
export function Templates({ batch }: { batch: ParsedBatch }) {
  const f = batch.features;
  return (
    <div className="grid gap-5">
      <p className="text-sm text-muted-foreground">
        {f.n_events.toLocaleString("en")} events in {f.n_templates} templates over{" "}
        {Math.round(f.duration_s / 60)} minutes ({f.events_per_min.toFixed(1)} a minute).{" "}
        {f.error_events} errors ({percent(f.error_ratio, 1)})
        {f.level_counts.WARN ? ` and ${f.level_counts.WARN} warnings` : ""}
        {f.distinct_nodes ? ` across ${f.distinct_nodes} nodes` : ""}.{" "}
        {batch.shards > 1 ? `Parsed by ${batch.shards} parsers at once` : "Parsed in one pass"}
        {batch.template_history ? `, judged against ${batch.template_history} known templates` : ""}
        .
      </p>
      <ul className="grid gap-2">
        {batch.templates.map((t) => (
          <li key={t.template_id} className="grid gap-1.5 rounded-lg bg-raised p-4">
            <p className="font-mono text-xs leading-5 break-all">{t.template}</p>
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
              <span className="tabular font-medium text-foreground">
                {t.count.toLocaleString("en")}x
              </span>
              {/* A per-level count only when the template mixes levels; one level is the total. */}
              {Object.entries(t.levels).map(([level, n], _, levels) => (
                <span
                  key={level}
                  className={
                    level === "WARN"
                      ? "text-sev2-fg"
                      : /ERR|FATAL|CRIT|SEVERE/.test(level)
                        ? "text-sev1-fg"
                        : undefined
                  }
                >
                  {levels.length > 1 ? `${level} ${n.toLocaleString("en")}` : level}
                </span>
              ))}
              {t.nodes ? <span>{t.nodes} nodes</span> : null}
              {t.components.length ? <span>{t.components.join(", ")}</span> : null}
              {t.novel ? (
                <span className="rounded-xs border border-primary/70 px-1 text-primary">new</span>
              ) : null}
              {t.error_like ? (
                <span className="rounded-xs border border-sev1-fg/60 px-1 text-sev1-fg">
                  error-like
                </span>
              ) : null}
              <Citations ids={[t.evidence_id]} />
            </p>
          </li>
        ))}
      </ul>
      <Guard guard={batch.guard} raw={batch.n_raw_lines} />
    </div>
  );
}

/** Past incidents retrieval found, with how they matched, and each retrieval attempt. */
export function Similar({ retrieval }: { retrieval: RetrievalResult }) {
  return (
    <div className="grid gap-5">
      {retrieval.incidents.length === 0 ? (
        <p className="text-sm text-muted-foreground">No similar incident was found in memory.</p>
      ) : (
        <ol className="grid gap-2">
          {retrieval.incidents.map((incident, i) => (
            <li key={incident.incident_id} className="grid gap-1.5 rounded-lg bg-raised p-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="tabular text-xs text-faint">#{i + 1}</span>
                <SeverityBadge
                  severity={isSeverity(incident.severity) ? incident.severity : null}
                  size="sm"
                />
                <span className="font-medium">{incident.title}</span>
                {incident.evidence_id ? <Citations ids={[incident.evidence_id]} /> : null}
              </div>
              <p className="text-sm text-muted-foreground">{incident.resolution}</p>
              <p className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-faint">
                <span>failure mode {incident.failure_mode.replaceAll("_", " ")}</span>
                <span className="tabular">keyword match {incident.lexical_score.toFixed(2)}</span>
                <span className="tabular">meaning match {incident.dense_score.toFixed(2)}</span>
                {incident.rerank_score != null ? (
                  <span className="tabular">rerank {incident.rerank_score.toFixed(2)}</span>
                ) : null}
                {incident.components?.length ? (
                  <span>components {incident.components.slice(0, 3).join(", ")}</span>
                ) : null}
                <span>{SOURCE[incident.source] ?? incident.source}</span>
              </p>
            </li>
          ))}
        </ol>
      )}
      {retrieval.attempts.length ? (
        <div className="grid gap-2">
          <h3 className="font-sans text-sm font-semibold">Retrieval attempts</h3>
          <ol className="grid gap-1.5 text-xs">
            {retrieval.attempts.map((a) => (
              <li key={a.attempt} className="grid gap-0.5 rounded-sm bg-sunken p-2">
                <span className="text-muted-foreground">
                  Attempt {a.attempt}
                  {a.widened ? " (widened)" : ""}: {a.candidates} candidates, grade{" "}
                  {a.grade.toFixed(2)}
                </span>
                <span className="font-mono break-words">{a.query}</span>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
    </div>
  );
}
