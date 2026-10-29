import Link from "next/link";

import { Results } from "@/components/site/results";
import { RunGraph, type GraphStep } from "@/components/site/run-graph";
import { SiteFooter } from "@/components/site/site-footer";
import { SiteHeader } from "@/components/site/site-header";
import { Limitations, Standards } from "@/components/site/standards";
import { TriageReplay } from "@/components/site/triage-replay";
import { Button } from "@/components/ui/button";
import { evaluation, replay, runFacts, type RunFacts } from "@/lib/site-data";
import { cn } from "@/lib/utils";

const ms = (value: number | undefined) =>
  value == null ? "" : value < 1 ? "under 1 ms" : `${Math.round(value)} ms`;

function steps(f: RunFacts): GraphStep[] {
  return [
    {
      title: "Plan the run",
      body: "The supervisor picks a strategy: how many parse workers, whether to investigate, and the run's budget of tokens, cost, steps and time.",
      fact: `Planned in ${ms(f.stageMs.plan)}.`,
      nodes: ["plan"],
    },
    {
      title: "Parse and guard the logs",
      body: "Workers group lines into templates with Drain, pseudonymise IP and e-mail addresses with a keyed hash, and quarantine lines that read like instructions to a model. Large inputs fan out across up to 32 workers.",
      fact: `${f.lines} lines became ${f.templates} templates; ${f.pseudonyms} addresses pseudonymised; ${f.quarantined} line quarantined.`,
      nodes: ["parse1", "parse2", "parse3", "parse4", "merge"],
    },
    {
      title: "Rate severity and recall the past, in parallel",
      body: "Rules and a calibrated model score the window. Conformal prediction turns the model's probabilities into a set that holds the true severity 90% of the time, and safety floors stop a dangerous pattern being rated too low. Meanwhile hybrid search finds similar past incidents.",
      fact: `${f.severity} at ${Math.round(f.probability * 100)}% probability; ${f.similar} similar past incidents found.`,
      nodes: ["severity", "recall"],
    },
    {
      title: "Investigate with read-only tools",
      body: "An agent proposes hypotheses and tests them through ARIA's MCP server: example lines for a template, a component's timeline, which nodes are affected, incident search, runbooks. Every result becomes evidence a claim can cite.",
      fact: `${f.toolCalls} tool calls; the leading hypothesis is supported at ${Math.round((f.leadingConfidence ?? 0) * 100)}%.`,
      nodes: ["investigate"],
    },
    {
      title: "Check there is enough to go on",
      body: "If no hypothesis holds up or the matches look weak, the graph widens the search and investigates again, at most twice. A quiet window with nothing new stops here.",
      fact:
        f.replans === 0
          ? "Enough evidence on the first pass; no replan."
          : `Replanned ${f.replans} times.`,
      nodes: ["assess"],
    },
    {
      title: "Write the report and draft the messages",
      body: "The report is written from evidence only. A validator rejects any claim whose citation is missing or whose numbers disagree with the evidence; with an LLM, a draft that fails falls back to the grounded template. Messages to Slack, Teams or a status page are drafted, never sent.",
      fact: `${f.claims} claims checked, ${Math.round(f.citationCoverage * 100)}% cited; ${f.actions} messages drafted.`,
      nodes: ["report", "comms"],
    },
    {
      title: "Wait for a person",
      body: "The graph pauses and keeps its checkpoint, through restarts if need be. A reviewer approves, edits or rejects, and only the messages they approve go out.",
      fact: `Ready for review ${(f.timeToReviewMs / 1000).toFixed(1)} s after the logs arrived.`,
      nodes: ["review"],
    },
    {
      title: "Publish and remember",
      body: "The approved report is stored, the incident joins memory so the next similar alert finds it, and routine log templates are learned so they stop looking new.",
      fact: `Published in ${ms(f.stageMs.publish)} after approval.`,
      nodes: ["publish"],
    },
  ];
}

function Section({
  id,
  title,
  intro,
  deferred = false,
  children,
}: {
  id: string;
  title: string;
  intro?: string;
  /** Skip layout and paint until the section nears the viewport (for sections far below the
   * fold that nothing measures on load). */
  deferred?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section
      id={id}
      aria-labelledby={`${id}-title`}
      className={cn(
        "scroll-mt-8 border-t border-rule",
        deferred && "[contain-intrinsic-size:auto_1400px] [content-visibility:auto]",
      )}
    >
      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-20 sm:px-6 lg:px-8 lg:py-28">
        <div className="grid max-w-3xl gap-4">
          <h2 id={`${id}-title`} className="text-3xl font-extrabold tracking-tight sm:text-4xl">
            {title}
          </h2>
          {intro ? <p className="text-lg text-muted-foreground">{intro}</p> : null}
        </div>
        {children}
      </div>
    </section>
  );
}

export default function Landing() {
  const data = replay();
  const facts = runFacts();
  const evals = evaluation();
  return (
    <>
      <a
        href="#main"
        className="sr-only z-50 rounded-sm bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to content
      </a>
      <SiteHeader />
      <main id="main">
        <div className="mx-auto grid max-w-7xl items-center gap-14 px-4 pt-10 pb-20 sm:px-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-12 lg:px-8 lg:pt-16 lg:pb-28">
          <div className="grid content-start gap-6">
            <h1 className="text-[2.75rem] leading-[1.04] font-extrabold tracking-[-0.03em] text-balance sm:text-6xl lg:text-[3.5rem] xl:text-[4rem]">
              Incident triage that shows its work.
            </h1>
            <p className="max-w-xl text-lg leading-relaxed text-muted-foreground">
              ARIA reads an alert and its logs, rates severity with calibrated confidence, checks
              what happened last time and drafts the incident report. Every claim cites the log
              line, rule or past incident behind it, and nothing is sent until a person approves.
            </p>
            <div className="flex flex-wrap gap-3">
              <Button asChild variant="primary" size="lg">
                <Link href="/console" prefetch={false}>
                  Open the console
                </Link>
              </Button>
              <Button asChild variant="secondary" size="lg">
                <a href="#results">See the measured results</a>
              </Button>
            </div>
            <p className="max-w-xl text-sm text-faint">
              The tag is a recording of a real run: {data.nLines} HDFS log lines (real Loghub lines,
              arranged into a synthetic incident) triaged offline. One line was planted to test the
              injection guard.
            </p>
          </div>
          <TriageReplay data={data} />
        </div>

        <Section
          id="how"
          title="What happens in a run"
          intro="A run is a LangGraph state machine with a checkpoint after every step, so it can stop for a person, carry on after a restart, or be rewound and forked. The numbers come from the recorded run above."
        >
          <RunGraph steps={steps(facts)} />
        </Section>

        <Section
          id="results"
          deferred
          title="Measured, caveats included"
          intro="ARIA is tested on incident windows built from real Loghub logs, against simpler baselines. Every number on this page comes from the committed evaluation results."
        >
          <Results data={evals} />
        </Section>

        <Section
          id="standards"
          deferred
          title="Built on open agent standards"
          intro="ARIA works with the tools you already have, through protocols other agents and frontends speak."
        >
          <Standards />
        </Section>

        <Section id="limits" title="Where it falls short" deferred>
          <Limitations />
        </Section>
      </main>
      <SiteFooter recordedAt={data.recordedAt} gitSha={data.gitSha} />
    </>
  );
}
