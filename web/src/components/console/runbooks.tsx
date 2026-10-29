"use client";

import { BookOpenIcon } from "lucide-react";
import Link from "next/link";

import { EmptyState, ErrorState, LoadingRows, PageHeader } from "@/components/console/states";
import { useRunbook, useRunbooks } from "@/lib/api/hooks";
import { ApiError } from "@/lib/api/client";
import type { RunbookStep } from "@/lib/api/types";
import { systemName } from "@/lib/systems";
import { cn } from "@/lib/utils";
import { useDocumentTitle } from "@/lib/document-title";

const RISK: Record<string, string> = {
  low: "border-rule text-muted-foreground",
  medium: "border-sev2-fg/60 text-sev2-fg",
  high: "border-sev1-fg/60 text-sev1-fg",
};

function Risk({ risk }: { risk: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center justify-self-start rounded-xs border px-1.5 text-[0.6875rem] font-medium",
        RISK[risk] ?? RISK.low,
      )}
    >
      {risk} risk
    </span>
  );
}

/** The runbooks ARIA can cite: steps come from these files, never from a model. */
export function Runbooks() {
  const runbooks = useRunbooks();
  return (
    <div className="grid gap-6">
      <PageHeader
        title="Runbooks"
        description="ARIA proposes next steps only from these runbooks, and cites the one it used. Edit them as Markdown in the repository's runbooks folder."
      />
      {runbooks.isPending ? (
        <LoadingRows rows={6} label="Loading runbooks" />
      ) : runbooks.isError ? (
        <ErrorState error={runbooks.error} onRetry={() => void runbooks.refetch()} />
      ) : runbooks.data.length === 0 ? (
        <EmptyState icon={BookOpenIcon} title="No runbooks are loaded">
          Add Markdown runbooks to the runbooks folder and run <code>aria seed</code>.
        </EmptyState>
      ) : (
        <ul className="grid gap-2 md:grid-cols-2">
          {runbooks.data.map((rb) => (
            <li
              key={rb.slug}
              className="relative grid gap-2 rounded-lg bg-raised p-5 transition-colors duration-(--duration-quick) focus-within:ring-2 focus-within:ring-ring hover:bg-raised/80"
            >
              <div className="flex items-start justify-between gap-3">
                <Link
                  href={`/console/runbooks/${encodeURIComponent(rb.slug)}` as never}
                  className="font-medium after:absolute after:inset-0 after:content-['']"
                >
                  {rb.title}
                </Link>
                <Risk risk={rb.risk} />
              </div>
              <p className="line-clamp-2 text-sm text-muted-foreground">
                <Text>{rb.when_to_use}</Text>
              </p>
              <p className="text-xs text-faint">
                {rb.systems.map(systemName).join(", ")}
                {rb.failure_modes.length
                  ? ` for ${rb.failure_modes.map((f) => f.replaceAll("_", " ")).join(", ")}`
                  : ""}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Runbook text uses Markdown backticks for commands; show those as code. */
function Text({ children }: { children: string }) {
  return (
    <>
      {children.split("`").map((part, i) =>
        i % 2 === 1 ? (
          <code key={i} className="rounded-xs bg-sunken px-1 py-0.5 text-[0.85em]">
            {part}
          </code>
        ) : (
          part
        ),
      )}
    </>
  );
}

function Steps({ title, steps }: { title: string; steps: RunbookStep[] }) {
  if (steps.length === 0) return null;
  return (
    <section className="grid gap-3">
      <h2 className="text-xl tracking-heading">{title}</h2>
      <ol className="grid gap-2.5">
        {steps.map((step, i) => (
          <li key={i} className="grid grid-cols-[1.75rem_1fr] gap-2">
            <span className="tabular flex size-6 items-center justify-center rounded-full border border-control text-xs font-medium">
              {i + 1}
            </span>
            <div className="grid gap-1">
              <p className="leading-relaxed">
                <Text>{step.text}</Text>
              </p>
              <Risk risk={step.risk} />
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function RunbookDetail({ slug }: { slug: string }) {
  const runbook = useRunbook(slug);
  useDocumentTitle(runbook.data?.title);
  if (runbook.isPending) return <LoadingRows rows={6} label="Loading the runbook" />;
  if (runbook.isError) {
    if (runbook.error instanceof ApiError && runbook.error.status === 404) {
      return (
        <EmptyState title="No runbook by that name">
          <Link href="/console/runbooks" className="underline">
            See all runbooks
          </Link>
        </EmptyState>
      );
    }
    return <ErrorState error={runbook.error} onRetry={() => void runbook.refetch()} />;
  }
  const rb = runbook.data;
  return (
    <article className="grid max-w-3xl gap-8">
      <nav aria-label="Breadcrumb" className="text-sm text-muted-foreground">
        <Link href="/console/runbooks" className="hover:text-foreground">
          Runbooks
        </Link>
        <span aria-hidden className="px-2 text-faint">
          /
        </span>
        <span aria-current="page" className="font-mono text-xs">
          {rb.slug}
        </span>
      </nav>
      <PageHeader
        title={rb.title}
        description={<Text>{rb.when_to_use}</Text>}
        actions={<Risk risk={rb.risk} />}
      >
        <p className="text-sm text-muted-foreground">
          {rb.systems.map(systemName).join(", ")}
          {rb.failure_modes.length
            ? `, for ${rb.failure_modes.map((f) => f.replaceAll("_", " ")).join(", ")}`
            : ""}
        </p>
      </PageHeader>
      <Steps title="Diagnose" steps={rb.diagnose} />
      <Steps title="Mitigate" steps={rb.mitigate} />
      <Steps title="Verify" steps={rb.verify} />
      {rb.escalate ? (
        <section className="grid gap-2">
          <h2 className="text-xl tracking-heading">Escalate</h2>
          <p className="leading-relaxed text-muted-foreground">
            <Text>{rb.escalate}</Text>
          </p>
        </section>
      ) : null}
    </article>
  );
}
