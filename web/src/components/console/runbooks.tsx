"use client";

import { ArrowLeftIcon, BookOpenIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef } from "react";

import { EmptyState, ErrorState, LoadingRows, PageHeader } from "@/components/console/states";
import { Button } from "@/components/ui/button";
import { CodeText } from "@/components/ui/code-text";
import { useRunbook, useRunbooks } from "@/lib/api/hooks";
import { ApiError } from "@/lib/api/client";
import type { RunbookOut, RunbookStep } from "@/lib/api/types";
import { systemName } from "@/lib/systems";
import { cn } from "@/lib/utils";
import { useDocumentTitle } from "@/lib/document-title";
import { failureName } from "@/lib/failure-modes";

// Risk is quiet text, not a badge: the calm budget keeps badges for what needs a decision. It
// keeps to ink and the danger red; the severity hues mean severity only.
const RISK: Record<string, string> = {
  low: "text-muted-foreground",
  medium: "text-muted-foreground",
  high: "font-medium text-danger",
};

function Risk({ risk }: { risk: string }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center justify-self-start text-xs whitespace-nowrap",
        RISK[risk] ?? RISK.low,
      )}
    >
      {risk} risk
    </span>
  );
}

const RISK_ORDER = ["low", "medium", "high"];

/** A runbook's risk is its riskiest step's, so a "low risk" runbook never holds a high-risk step. */
export function highestRisk(rb: Pick<RunbookOut, "risk" | "diagnose" | "mitigate" | "verify">) {
  const all = [rb.risk, ...[...rb.diagnose, ...rb.mitigate, ...rb.verify].map((s) => s.risk)];
  return all.reduce((top, risk) =>
    RISK_ORDER.indexOf(risk) > RISK_ORDER.indexOf(top) ? risk : top,
  );
}

/** What a runbook covers, in words: "HDFS, for block serve exceptions" or "Any system". */
function covers(rb: { systems: string[]; failure_modes: string[] }): string {
  const systems = rb.systems.includes("*") ? "Any system" : rb.systems.map(systemName).join(", ");
  const modes = rb.failure_modes.filter((f) => f !== "*").map(failureName);
  return modes.length ? `${systems}, for ${modes.join(", ")}` : systems;
}

/** The runbooks ARIA can cite: steps come from these files, never from a model. */
export function Runbooks() {
  const runbooks = useRunbooks();
  return (
    <div className="grid gap-6">
      <PageHeader
        title="Runbooks"
        description="ARIA proposes next steps only from these runbooks, and cites the one it used. A team adds its own as short text files kept with ARIA. A runbook's risk is that of its riskiest step."
      />
      {runbooks.isPending ? (
        <LoadingRows rows={6} label="Loading runbooks" />
      ) : runbooks.isError ? (
        <ErrorState
          title="Runbooks could not be loaded"
          error={runbooks.error}
          onRetry={() => void runbooks.refetch()}
        />
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
                <Risk risk={highestRisk(rb)} />
              </div>
              <p className="line-clamp-2 text-sm text-muted-foreground">
                <CodeText>{rb.when_to_use}</CodeText>
              </p>
              <p className="text-xs text-faint">{covers(rb)}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Runbook text uses Markdown backticks for commands; show those as code. */
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
                <CodeText>{step.text}</CodeText>
              </p>
              {/* Most steps are low risk; only the ones to think twice about are tagged. */}
              {step.risk !== "low" ? <Risk risk={step.risk} /> : null}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

/**
 * Focus on the page's title once it has loaded, as on an incident page. The runbook's name only
 * arrives with the runbook, after the page has been announced by its address, so this is when a
 * screen reader hears which runbook opened. The title takes focus on every arrival, so it shows
 * no ring.
 */
function useTitleFocus<T extends HTMLElement>() {
  const page = useRef<T>(null);
  useEffect(() => {
    const title = page.current?.querySelector("h1");
    if (!title) return;
    title.tabIndex = -1;
    title.focus({ preventScroll: true });
  }, []);
  return page;
}

function MissingRunbook() {
  const page = useTitleFocus<HTMLDivElement>();
  return (
    <div ref={page} className="[&_h1]:outline-none">
      <EmptyState heading="h1" title="No runbook by that name">
        <Link href="/console/runbooks" className="underline">
          See all runbooks
        </Link>
      </EmptyState>
    </div>
  );
}

export function RunbookDetail({ slug }: { slug: string }) {
  const runbook = useRunbook(slug);
  const missing = runbook.error instanceof ApiError && runbook.error.status === 404;
  useDocumentTitle(runbook.data?.title ?? (missing ? "Runbook not found" : null));
  if (runbook.isPending) return <LoadingRows rows={6} label="Loading the runbook" />;
  if (runbook.isError) {
    if (missing) return <MissingRunbook />;
    return (
      <ErrorState
        title="This runbook could not be loaded"
        error={runbook.error}
        onRetry={() => void runbook.refetch()}
        action={
          <Button asChild size="sm" variant="ghost">
            <Link href="/console/runbooks">See all runbooks</Link>
          </Button>
        }
      />
    );
  }
  return <Runbook rb={runbook.data} />;
}

function Runbook({ rb }: { rb: RunbookOut }) {
  const page = useTitleFocus<HTMLElement>();
  return (
    <article ref={page} className="grid max-w-3xl gap-8 [&_h1]:outline-none">
      <nav
        aria-label="Breadcrumb"
        className="flex min-w-0 items-center text-sm text-muted-foreground"
      >
        <Link
          href="/console/runbooks"
          className="inline-flex min-h-6 shrink-0 items-center hover:text-foreground"
        >
          Runbooks
        </Link>
        <span aria-hidden className="shrink-0 px-2 text-faint">
          /
        </span>
        <span aria-current="page" className="min-w-0 truncate">
          {rb.title}
        </span>
      </nav>
      <PageHeader
        title={rb.title}
        description={<CodeText>{rb.when_to_use}</CodeText>}
        actions={<Risk risk={highestRisk(rb)} />}
      >
        <p className="text-sm text-muted-foreground">{covers(rb)}</p>
        <p className="max-w-prose text-sm text-muted-foreground">
          Steps marked medium or high risk could make things worse if done wrongly. ARIA flags them
          in its reports, for a person to approve before anyone acts on them.
        </p>
      </PageHeader>
      <Steps title="Diagnose" steps={rb.diagnose} />
      <Steps title="Mitigate" steps={rb.mitigate} />
      <Steps title="Verify" steps={rb.verify} />
      {rb.escalate ? (
        <section className="grid gap-2">
          <h2 className="text-xl tracking-heading">Escalate</h2>
          <p className="leading-relaxed text-muted-foreground">
            <CodeText>{rb.escalate}</CodeText>
          </p>
        </section>
      ) : null}
      <Link
        href="/console/runbooks"
        className="inline-flex w-fit items-center gap-1.5 text-sm underline underline-offset-4"
      >
        <ArrowLeftIcon aria-hidden className="size-4" />
        All runbooks
      </Link>
    </article>
  );
}
