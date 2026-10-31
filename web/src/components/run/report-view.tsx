"use client";

import { CircleCheckIcon, CircleAlertIcon, ShieldAlertIcon } from "lucide-react";
import Link from "next/link";

import { CodeText } from "@/components/ui/code-text";
import type { Claim, IncidentReport } from "@/lib/api/types";
import { percent, stripSeverity, writtenOffline } from "@/lib/format";
import { cn } from "@/lib/utils";

import { Citations } from "./evidence";

function ClaimList({ claims }: { claims: Claim[] }) {
  return (
    <ul className="grid gap-3">
      {claims.map((claim, i) => (
        <li
          key={`${i}-${claim.text}`}
          className="grid grid-cols-[0.75rem_minmax(0,1fr)] gap-2 leading-relaxed"
        >
          <span aria-hidden className="mt-2.5 block size-1.5 rounded-full bg-control" />
          <p>
            <CodeText>{claim.text}</CodeText> <Citations ids={claim.evidence_ids ?? []} />
          </p>
        </li>
      ))}
    </ul>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="grid gap-3">
      <h3 className="font-sans text-sm font-semibold text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}

// Risk keeps to ink and the danger red: the severity hues mean severity only.
const RISK: Record<string, string> = {
  low: "text-muted-foreground",
  medium: "text-foreground",
  high: "text-danger",
};

const STATUS: Record<string, string> = {
  draft: "draft, nothing sent yet",
  published: "published",
  rejected: "discarded",
};

/**
 * The report as it will be published (or was): ARIA's conclusions, next steps and open
 * questions, each claim with its sources. When it happened, and the incidents seen before, are
 * the panels above it. `titleHidden` drops the report's own title when the page's heading
 * already says the same thing.
 */
export function ReportView({
  report,
  titleHidden = false,
}: {
  report: IncidentReport;
  titleHidden?: boolean;
}) {
  const validation = report.validation;
  const ok = validation?.ok ?? false;
  return (
    <article
      aria-labelledby="report-title"
      className="grid gap-7 rounded-lg bg-raised p-5 wrap-anywhere"
    >
      <header className="grid gap-2">
        <h2 id="report-title" className="text-base font-medium">
          The report
        </h2>
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span>
            Version {report.version ?? 1}, {STATUS[report.status ?? "draft"] ?? report.status}
          </span>
          <span>
            written by{" "}
            {writtenOffline(report)
              ? "ARIA's evidence template (offline mode)"
              : `a language model (${report.model ?? "model"})`}
          </span>
          <span
            className={cn(
              "inline-flex items-center gap-1 font-medium",
              ok ? "text-ok" : "text-danger",
            )}
          >
            {ok ? (
              <CircleCheckIcon aria-hidden className="size-3.5" />
            ) : (
              <CircleAlertIcon aria-hidden className="size-3.5" />
            )}
            {ok
              ? `Validated: ${validation?.checked_claims ?? 0} claims, ${percent(validation?.citation_coverage ?? 0)} cited`
              : "Failed validation"}
          </span>
        </p>
        {titleHidden ? null : (
          <p className="text-xl leading-tight tracking-heading">{stripSeverity(report.title)}</p>
        )}
        {!ok && validation?.issues?.length ? (
          <ul className="grid gap-1 rounded-lg bg-danger/10 p-4 text-sm">
            {validation.issues.map((issue, i) => (
              <li key={i} className={issue.level === "error" ? "text-danger" : "text-sev3-fg"}>
                {issue.path ? <code className="mr-1">{issue.path}</code> : null}
                {issue.message}
              </li>
            ))}
          </ul>
        ) : null}
      </header>

      <Section title="Summary">
        <ClaimList claims={report.summary} />
      </Section>
      {report.impact?.length ? (
        <Section title="Impact">
          <ClaimList claims={report.impact} />
        </Section>
      ) : null}
      {report.suspected_cause?.length ? (
        <Section title="Suspected cause">
          <ClaimList claims={report.suspected_cause} />
        </Section>
      ) : null}
      {report.actions?.length ? (
        <Section title="Next steps">
          <ol className="grid gap-3">
            {report.actions.map((action, i) => (
              <li key={i} className="grid grid-cols-[1.75rem_1fr] gap-2 leading-relaxed">
                <span className="tabular flex size-6 items-center justify-center rounded-full border border-control text-xs font-medium">
                  {i + 1}
                </span>
                <div>
                  <p>
                    <CodeText>{action.text}</CodeText> <Citations ids={action.evidence_ids ?? []} />
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    <span className={RISK[action.risk ?? "low"]}>{action.risk ?? "low"} risk</span>
                    {action.runbook_slug ? (
                      <>
                        {", from runbook "}
                        <Link
                          href={
                            `/console/runbooks/${encodeURIComponent(action.runbook_slug)}` as never
                          }
                          className="underline decoration-control underline-offset-2 hover:decoration-foreground"
                        >
                          {action.runbook_slug}
                        </Link>
                      </>
                    ) : null}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </Section>
      ) : null}
      {report.open_questions?.length ? (
        <Section title="Open questions">
          <ul className="grid list-disc gap-1.5 pl-5 text-muted-foreground">
            {report.open_questions.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ul>
        </Section>
      ) : null}
      {report.status === "draft" ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <ShieldAlertIcon aria-hidden className="size-4" />
          Draft: nothing has been sent. A reviewer must approve it first.
        </p>
      ) : null}
    </article>
  );
}

/** Model output while the report is being written (live only; tokens are never stored). */
export function LiveDraft({ text }: { text: string }) {
  return (
    <section aria-label="Report being written" className="grid gap-2 rounded-lg bg-sunken p-5">
      <p className="flex items-center gap-2 text-sm font-medium">
        <span aria-hidden className="block size-2 animate-pulse-dot rounded-full bg-primary" />
        Writing the report
      </p>
      <pre
        tabIndex={0}
        role="region"
        aria-label="Report text so far"
        className="max-h-80 overflow-auto font-mono text-xs leading-5 whitespace-pre-wrap text-muted-foreground"
      >
        {text.slice(-4000)}
      </pre>
    </section>
  );
}
