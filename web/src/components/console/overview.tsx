"use client";

import { InboxIcon, PlusIcon } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { SEVERITY_BG } from "@/components/aria/severity";
import { AllClearSpot, WelcomeSpot } from "@/components/illustrations/spots";
import { RunRow } from "@/components/console/run-row";
import { EmptyState, ErrorState, LoadingRows, PageHeader } from "@/components/console/states";
import { RunStatus } from "@/components/console/status";
import { ArrowCircle, Button } from "@/components/ui/button";
import samples from "@/data/samples.json";
import { useProviders, useRuns } from "@/lib/api/hooks";
import { isSeverity, SEVERITIES, type RunSummary, type Severity } from "@/lib/api/types";
import { duration, median, money, percent } from "@/lib/format";
import { cn } from "@/lib/utils";

const DAY_MS = 24 * 3600 * 1000;

function summarize(runs: RunSummary[]) {
  const now = Date.now();
  const recent = runs.filter((r) => now - new Date(r.created_at).getTime() < DAY_MS);
  const rated = runs.filter((r) => isSeverity(r.severity));
  const mix = Object.fromEntries(SEVERITIES.map((s) => [s, 0])) as Record<Severity, number>;
  for (const r of rated) mix[r.severity as Severity] += 1;
  const latencies = runs.map((r) => r.latency_ms).filter((v): v is number => v != null);
  // Rules or the model decided alone; "fallback" means ARIA was unsure and asked a person.
  const automatic = rated.filter(
    (r) => r.decided_by === "rules" || r.decided_by === "model",
  ).length;
  return {
    total: runs.length,
    today: recent.length,
    waiting: runs.filter((r) => r.status === "awaiting_review"),
    running: runs.filter((r) => r.status === "running" || r.status === "queued").length,
    failed: runs.filter((r) => r.status === "failed").length,
    mix,
    rated: rated.length,
    medianLatency: median(latencies),
    automaticShare: rated.length ? automatic / rated.length : null,
    tokens: runs.reduce((sum, r) => sum + (r.tokens_in ?? 0) + (r.tokens_out ?? 0), 0),
    cost: runs.reduce((sum, r) => sum + (r.cost_usd ?? 0), 0),
  };
}

/** A statistic: the number first, then its name and what it counts. Words ("None yet") are set
 * smaller and quieter than numbers, so an empty console does not shout. */
function Fact({ label, value, note }: { label: string; value: string; note?: string }) {
  const numeric = /\d/.test(value);
  return (
    <div className="grid content-start gap-3 rounded-lg bg-raised p-5 sm:p-6">
      <dt className="eyebrow order-2 text-foreground">{label}</dt>
      <dd
        className={cn(
          "stat order-1",
          numeric ? "text-4xl" : "flex h-[3.3125rem] items-end text-2xl text-muted-foreground",
        )}
      >
        {value}
      </dd>
      {note ? <dd className="order-3 -mt-1.5 text-sm text-muted-foreground">{note}</dd> : null}
    </div>
  );
}

function SeverityMix({ mix, rated }: { mix: Record<Severity, number>; rated: number }) {
  if (rated === 0) return <p className="text-sm text-muted-foreground">No rated runs yet.</p>;
  return (
    <figure className="grid gap-3">
      <div
        className="flex h-4 w-full overflow-hidden rounded-xs bg-sunken"
        role="img"
        aria-label={SEVERITIES.map((s) => `${s} ${mix[s]}`).join(", ")}
      >
        {SEVERITIES.filter((s) => mix[s] > 0).map((s) => (
          <span
            key={s}
            className={cn("h-full border-r border-background last:border-r-0", SEVERITY_BG[s])}
            style={{ width: `${(mix[s] / rated) * 100}%` }}
          />
        ))}
      </div>
      <figcaption className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
        {SEVERITIES.map((s) => (
          <span key={s} className="inline-flex items-center gap-1.5">
            <span aria-hidden className={cn("block size-2.5 rounded-xs", SEVERITY_BG[s])} />
            <span className="font-medium">{s}</span>
            <span className="tabular text-muted-foreground">{mix[s]}</span>
          </span>
        ))}
      </figcaption>
    </figure>
  );
}

/** A way in for a first visit, shown until a handful of runs exist. */
function StartHere() {
  return (
    <section
      aria-labelledby="start-title"
      className="grid items-center gap-6 rounded-lg bg-raised p-6 sm:p-8 md:grid-cols-[minmax(0,1fr)_14rem]"
    >
      <div className="grid justify-items-start gap-3">
        <p className="eyebrow text-muted-foreground">New to ARIA?</p>
        <h2 id="start-title" className="text-2xl leading-tight tracking-heading sm:text-3xl">
          Triage a sample in one click
        </h2>
        <p className="max-w-2xl text-muted-foreground">
          Pick one of {samples.length} short incidents built from real logs and watch ARIA work
          through it. The guide also explains how to read a run and the words ARIA uses.
        </p>
        <Button asChild variant="primary" size="md" className="mt-2 pr-1.5">
          <Link href="/console/guide">
            Open the guide
            <ArrowCircle tone="white" size="md" />
          </Link>
        </Button>
      </div>
      <WelcomeSpot className="hidden h-auto w-full md:block" />
    </section>
  );
}

export function Overview() {
  const runs = useRuns("all", 200);
  const providers = useProviders();
  const stats = useMemo(() => summarize(runs.data?.runs ?? []), [runs.data]);
  const waiting = [...stats.waiting].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  );
  // Runs waiting for review are listed above; this list is the rest, newest first.
  const finished = (runs.data?.runs ?? []).filter((r) => r.status !== "awaiting_review");
  const live =
    providers.data?.filter((p) => p.enabled && p.kind !== "fake" && p.kind !== "local") ?? [];

  return (
    <div className="grid gap-10">
      <PageHeader
        title="Overview"
        description={
          !runs.data
            ? "Recent runs at a glance."
            : stats.total === 0
              ? "Nothing has run yet. A sample below takes seconds."
              : `The last ${stats.total.toLocaleString("en")} runs at a glance.`
        }
        actions={
          <Button asChild variant="primary">
            <Link href="/console/runs/new">
              <PlusIcon aria-hidden />
              New triage
            </Link>
          </Button>
        }
      />

      {runs.isPending ? (
        <LoadingRows rows={4} label="Loading runs" />
      ) : runs.isError ? (
        <ErrorState
          title="Recent runs could not be loaded"
          error={runs.error}
          onRetry={() => void runs.refetch()}
        />
      ) : (
        <>
          {stats.total < 5 ? <StartHere /> : null}

          <section aria-labelledby="waiting-title" className="grid gap-4">
            <div className="flex items-baseline justify-between gap-4">
              <h2 id="waiting-title" className="text-xl tracking-heading">
                Waiting for review
              </h2>
              {waiting.length > 0 ? (
                <p className="text-sm text-muted-foreground">Oldest first</p>
              ) : null}
            </div>
            {waiting.length === 0 ? (
              <EmptyState
                icon={InboxIcon}
                art={<AllClearSpot className="h-auto w-full" />}
                title="Nothing is waiting for review"
                action={
                  <Button asChild size="sm">
                    <Link href="/console/runs/new">Start a triage</Link>
                  </Button>
                }
              >
                New runs pause here once their report is ready. Alerts from Alertmanager or Grafana
                start runs on their own.
              </EmptyState>
            ) : (
              <ul className="grid gap-2">
                {waiting.slice(0, 6).map((run) => (
                  <RunRow key={run.id} run={run} action="review" />
                ))}
              </ul>
            )}
            {waiting.length > 6 ? (
              <Link
                href="/console/runs?status=awaiting_review"
                className="justify-self-start text-sm font-medium underline decoration-control underline-offset-4 hover:decoration-foreground"
              >
                See all {waiting.length} waiting
              </Link>
            ) : null}
          </section>

          <section aria-labelledby="facts-title" className="grid gap-6">
            <h2 id="facts-title" className="text-xl tracking-heading">
              How ARIA is doing
            </h2>
            <dl className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <Fact label="Runs in the last 24 hours" value={stats.today.toLocaleString("en")} />
              <Fact
                label="Median time to review"
                value={duration(stats.medianLatency) || "None yet"}
                note="from logs in to report ready"
              />
              <Fact
                label="Decided without a person"
                value={percent(stats.automaticShare) || "None yet"}
                note="rules or the calibrated model alone"
              />
              <Fact
                label="LLM tokens used"
                value={stats.tokens ? stats.tokens.toLocaleString("en") : "None"}
                note={
                  stats.tokens
                    ? stats.cost
                      ? `${money(stats.cost)} spent`
                      : "no spend recorded"
                    : "offline mode: no LLM"
                }
              />
            </dl>
            <div className="grid gap-3">
              <h3 className="eyebrow text-muted-foreground">Severity of rated runs</h3>
              <SeverityMix mix={stats.mix} rated={stats.rated} />
            </div>
          </section>

          <section aria-labelledby="recent-title" className="grid gap-4">
            <div className="flex items-baseline justify-between gap-4">
              <h2 id="recent-title" className="text-xl tracking-heading">
                Recently finished
              </h2>
              <Link
                href="/console/runs"
                className="text-sm font-medium underline decoration-control underline-offset-4 hover:decoration-foreground"
              >
                All incidents
              </Link>
            </div>
            {finished.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {stats.total === 0 ? "No runs yet." : "No run has finished yet."}
              </p>
            ) : (
              <ul className="grid gap-2">
                {finished.slice(0, 6).map((run) => (
                  <RunRow key={run.id} run={run} />
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby="providers-title" className="grid gap-3">
            <h2 id="providers-title" className="text-xl tracking-heading">
              Model providers
            </h2>
            {providers.isPending ? (
              <LoadingRows rows={1} label="Loading providers" />
            ) : providers.isError ? (
              <ErrorState error={providers.error} title="Providers could not be loaded" />
            ) : live.length === 0 ? (
              <p className="max-w-prose text-sm text-muted-foreground">
                No LLM provider is configured, so ARIA runs deterministically: rules and the
                calibrated model rate severity and reports come from the grounded template. Set
                NVIDIA_API_KEY (or another provider) to add model-written narratives.
              </p>
            ) : (
              <ul className="flex flex-wrap gap-2">
                {live.map((p) => (
                  <li
                    key={p.name}
                    className="inline-flex items-center gap-2 rounded-md bg-raised px-3 py-1.5 text-sm"
                  >
                    <span
                      aria-hidden
                      className={cn(
                        "block size-2 rounded-full",
                        p.breaker === "closed" ? "bg-ok" : "bg-sev3",
                      )}
                    />
                    <span className="font-medium">{p.name}</span>
                    <span className="text-muted-foreground">{p.chat_model}</span>
                    {p.breaker !== "closed" ? (
                      <span className="text-xs text-sev3-fg">circuit {p.breaker}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </section>
          {stats.running > 0 || stats.failed > 0 ? (
            <p className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
              {stats.running > 0 ? (
                <span className="inline-flex items-center gap-1">
                  <RunStatus status="running" /> {stats.running} in progress
                </span>
              ) : null}
              {stats.failed > 0 ? (
                <Link
                  href="/console/runs?status=failed"
                  className="inline-flex items-center gap-1 hover:underline"
                >
                  <RunStatus status="failed" /> {stats.failed} failed
                </Link>
              ) : null}
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}
