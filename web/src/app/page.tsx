import { Suspense, type ReactNode } from "react";

import { Term } from "@/components/aria/term";
import { Closing } from "@/components/site/closing";
import { Explainer } from "@/components/site/explainer";
import { Faq } from "@/components/site/faq";
import { Hero } from "@/components/site/hero";
import { ResultsRow } from "@/components/site/results-row";
import { RunGraph, type GraphStep } from "@/components/site/run-graph";
import { SiteFooter } from "@/components/site/site-footer";
import { SiteHeader } from "@/components/site/site-header";
import { TriageReplay } from "@/components/site/triage-replay";
import { WakeApi } from "@/components/site/wake-api";
import { Why } from "@/components/site/why";
import {
  evaluation,
  realData,
  realLogs,
  replay,
  runFacts,
  type Replay,
  type RunFacts,
} from "@/lib/site-data";
import { cn } from "@/lib/utils";

/** How a run works, in four steps (item 28), each with what happened in the recorded run. */
function steps(f: RunFacts, target: number): GraphStep[] {
  return [
    {
      title: "Read the logs",
      body: (
        <>
          ARIA groups the lines into <Term name="log-template">templates</Term>, swaps IP and e-mail
          addresses for stand-ins (it <Term name="pseudonymise">pseudonymises</Term> them) and sets
          aside lines that read like instructions to a model (they are{" "}
          <Term name="quarantine">quarantined</Term>). A large input is split across workers.
        </>
      ),
      fact: `${f.lines} lines became ${f.templates} templates; ${f.pseudonyms} addresses replaced; ${f.quarantined} planted line set aside.`,
      nodes: ["plan", "parse1", "parse2", "parse3", "parse4", "merge"],
    },
    {
      title: "Rate how serious it is, and recall the past",
      body: (
        <>
          Rules and a <Term name="calibrated">calibrated</Term> model score the logs and keep a{" "}
          <Term name="prediction-set">short list</Term> of levels, built to hold the right one{" "}
          {Math.round(target * 100)} times in 100. <Term name="safety-floor">Safety floors</Term>{" "}
          stop a dangerous pattern being rated too low. Meanwhile, search finds similar past
          incidents.
        </>
      ),
      fact: `${f.severity} at ${Math.round(f.probability * 100)}% probability; ${f.similar} similar past incidents found.`,
      nodes: ["severity", "recall"],
    },
    {
      title: "Investigate and write the report",
      body: (
        <>
          An agent tests its ideas with read-only tools (ARIA&apos;s{" "}
          <Term name="mcp">MCP server</Term>): example lines, a component&apos;s timeline, past
          incidents and <Term name="runbook">runbooks</Term>. Each result becomes{" "}
          <Term name="evidence">evidence</Term>. The report is written from evidence only, and a
          check rejects any claim whose source is missing. When the evidence is thin, ARIA widens
          the search and tries again (a{" "}
          <span className="whitespace-nowrap">
            <Term name="replan">replan</Term>),
          </span>{" "}
          at most twice.
        </>
      ),
      fact: `${f.toolCalls} tool calls; ${f.claims} claims checked, ${Math.round(f.citationCoverage * 100)}% cited; ${f.actions} messages drafted.`,
      nodes: ["investigate", "assess", "report", "comms"],
    },
    {
      title: "Wait for a person, then remember",
      body: (
        <>
          The run pauses and keeps its <Term name="checkpoint">checkpoint</Term>. A reviewer
          approves, edits or discards the messages, and only what they approve goes out. The
          approved incident joins ARIA&apos;s memory, so the next similar alert finds it.
        </>
      ),
      fact: `Ready for review ${(f.timeToReviewMs / 1000).toFixed(1)} s after the logs arrived.`,
      nodes: ["review", "publish"],
    },
  ];
}

type Tone = "cream" | "keylime" | "mint" | "sage" | "slate";

const PANEL: Record<Tone, string> = {
  cream: "",
  keylime: "bg-panel-keylime",
  mint: "bg-panel-mint",
  sage: "bg-panel-sage",
  slate: "bg-panel-slate",
};

/**
 * A section: a small tag, the serif heading and its subhead, left-aligned as in the reference,
 * on the cream page or inside one tinted panel.
 */
function Section({
  id,
  tag,
  title,
  intro,
  tone = "cream",
  deferred = false,
  children,
}: {
  id: string;
  tag: string;
  title: ReactNode;
  intro?: ReactNode;
  tone?: Tone;
  /** Skip layout and paint until the section nears the viewport (for sections far below the
   * fold that nothing measures on load). */
  deferred?: boolean;
  children: ReactNode;
}) {
  const panel = tone !== "cream";
  return (
    <section
      id={id}
      aria-labelledby={`${id}-title`}
      className={cn(
        "mx-auto max-w-[75rem] px-3 sm:px-6",
        deferred && "[contain-intrinsic-size:auto_1400px] [content-visibility:auto]",
      )}
    >
      <div
        className={cn(
          "grid gap-10 lg:gap-14",
          panel
            ? `rounded-card px-5 py-12 sm:px-10 sm:py-16 lg:px-12 ${PANEL[tone]}`
            : "py-16 lg:py-24",
        )}
      >
        <div className="grid max-w-3xl gap-4">
          <span className={cn("tag justify-self-start", panel && "bg-raised")}>{tag}</span>
          <h2 id={`${id}-title`} className="text-display">
            {title}
          </h2>
          {intro ? <p className="text-lead max-w-[62ch]">{intro}</p> : null}
        </div>
        {children}
      </div>
    </section>
  );
}

/** Who did the model's part of the recorded run, in a sentence. */
function writtenBy(data: Replay): string {
  return data.model
    ? `A language model, ${data.model.service} (${data.model.name}), investigated, chose the level from the short list, and wrote the report and the messages.`
    : "It ran offline, with no language model.";
}

export default function Landing() {
  const data = replay();
  const facts = runFacts();
  const evals = evaluation();
  const real = realLogs();
  const datasets = realData();
  // The HDFS log plus every other real dataset on Test results.
  const nDatasets = Object.keys(datasets).length + 1;
  return (
    <>
      <a
        href="#main"
        className="sr-only z-50 rounded-sm bg-primary px-4 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to content
      </a>
      <SiteHeader />
      <WakeApi />
      <main id="main">
        <Hero data={data} />

        <Section
          id="what"
          tag="What it does"
          title="What ARIA does for the person on call"
          intro="When an alert fires, ARIA has already read the logs. It says how serious the incident is and how sure it is, what changed, what fixed it last time, and drafts the messages for you to approve."
        >
          <Why />
          <Explainer lines={data.fileLines} />
        </Section>

        <Section
          id="run"
          tone="sage"
          tag="Example"
          title="One incident, start to finish"
          intro={
            <>
              {data.nLines} real HDFS log lines from Loghub, arranged into an incident, plus one
              planted line that tries to trick ARIA. {writtenBy(data)} Point at or tap a citation
              such as <span className="font-mono text-foreground">E2</span> to see the lines behind
              a claim. A sample you run in the console is a fresh incident built from lines like
              these, so its rating can differ.
            </>
          }
        >
          {/* Suspense boundaries let React hydrate each interactive section as its own, shorter
              task, so no single task blocks the main thread for long on a slow phone. */}
          <Suspense>
            <TriageReplay data={data} />
          </Suspense>
        </Section>

        <Section
          id="how"
          tag="How it works"
          title="Four steps, then a person decides"
          intro="Each step saves its place, so a triage can stop for a person, carry on after a restart, or be rewound and tried another way. The figures come from the example above. Words with a dotted underline open a short definition."
        >
          <Suspense>
            <RunGraph steps={steps(facts, evals.severity.targetCoverage)} />
          </Suspense>
        </Section>

        <Section
          id="results"
          tone="keylime"
          deferred
          tag="Results"
          title="What the tests show"
          intro={`ARIA is tested on ${nDatasets} public, labelled datasets, each against a simpler method. Four of the findings, including one where it falls short:`}
        >
          <ResultsRow data={evals} real={real} more={datasets} />
        </Section>

        <Closing />

        <section
          id="faq"
          aria-labelledby="faq-title"
          className="mx-auto max-w-[75rem] px-3 py-16 sm:px-6 lg:py-24"
        >
          <Faq />
        </section>
      </main>
      <SiteFooter recordedAt={data.recordedAt} />
    </>
  );
}
