"use client";

import { useId, useMemo, useState } from "react";

import type { Evidence, GuardReport, ParsedBatch } from "@/lib/api/types";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useDensity } from "@/lib/density";
import { capitalise, percent } from "@/lib/format";
import { cn } from "@/lib/utils";

import { DensityToggle } from "./density-toggle";
import { Citations, EvidenceChip, KIND_LABEL, sourceLabel, useEvidence } from "./evidence";

/** All evidence the run collected, filterable by kind. */
export function EvidenceTable({ evidence, cited }: { evidence: Evidence[]; cited: Set<string> }) {
  const [kind, setKind] = useState<string>("all");
  const { active, pin } = useEvidence();
  const kinds = useMemo(() => {
    const counts = new Map<string, number>();
    for (const e of evidence) counts.set(e.kind, (counts.get(e.kind) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [evidence]);
  const shown = kind === "all" ? evidence : evidence.filter((e) => e.kind === kind);
  const compact = useDensity() === "compact";
  const id = useId();
  return (
    <div className="grid gap-4">
      {/* One quiet control instead of a chip per kind: the calm budget allows four badges. */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm">
          <label htmlFor={`${id}-kind`} className="text-muted-foreground">
            Show
          </label>
          <Select value={kind} onValueChange={setKind}>
            <SelectTrigger id={`${id}-kind`} className="h-8 w-auto min-w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {[["all", evidence.length] as const, ...kinds].map(([k, n]) => (
                <SelectItem key={k} value={k}>
                  {k === "all" ? "All evidence" : capitalise(KIND_LABEL[k] ?? k)} ({n})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <DensityToggle />
      </div>
      <ul className={cn("grid", compact ? "gap-0.5" : "gap-1.5")}>
        {shown.map((e) => (
          <li
            key={e.id}
            className={cn(
              "grid grid-cols-[3.75rem_1fr] items-baseline gap-3 rounded-sm px-2 text-sm",
              compact ? "py-0.5" : "py-1.5",
              active === e.id && "bg-highlight",
            )}
          >
            <EvidenceChip id={e.id} />
            <button type="button" onClick={() => pin(e.id)} className="min-w-0 text-left">
              <span className="block truncate">{e.title}</span>
              <span className="block text-xs text-muted-foreground">
                {KIND_LABEL[e.kind] ?? e.kind}, from {sourceLabel(e.source)}
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
  const compact = useDensity() === "compact";
  return (
    <div className="grid gap-5">
      <p className="text-sm text-muted-foreground">
        {f.n_events.toLocaleString("en")} events in {f.n_templates} templates over{" "}
        {Math.round(f.duration_s / 60)} minutes ({f.events_per_min.toFixed(1)} a minute).{" "}
        {f.error_events} errors ({percent(f.error_ratio, 1)})
        {f.level_counts.WARN ? ` and ${f.level_counts.WARN} warnings` : ""}
        {f.distinct_nodes
          ? ` across ${f.distinct_nodes} ${f.distinct_nodes === 1 ? "server" : "servers"}`
          : ""}
        . {batch.shards > 1 ? `Parsed by ${batch.shards} parsers at once` : "Parsed in one pass"}
        {batch.template_history ? `, judged against ${batch.template_history} known templates` : ""}
        .
      </p>
      <DensityToggle className="justify-self-end" />
      <ul className={cn("grid", compact ? "gap-1" : "gap-2")}>
        {batch.templates.map((t) => (
          <li
            key={t.template_id}
            className={cn("grid rounded-lg bg-raised", compact ? "gap-1 px-3 py-2" : "gap-1.5 p-4")}
          >
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
              {t.nodes ? (
                <span>
                  {t.nodes} {t.nodes === 1 ? "server" : "servers"}
                </span>
              ) : null}
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
