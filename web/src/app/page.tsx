import { Suspense, type ReactNode } from "react";

import { Term } from "@/components/aria/term";
import { Closing } from "@/components/site/closing";
import { Faq } from "@/components/site/faq";
import { Hero } from "@/components/site/hero";
import { Converge, Rings } from "@/components/site/line-art";
import { ProofTicker } from "@/components/site/proof-ticker";
import { RealDatasets } from "@/components/site/real-datasets";
import { RealProof } from "@/components/site/real-proof";
import { Results } from "@/components/site/results";
import { RunGraph, type GraphStep } from "@/components/site/run-graph";
import { SiteFooter } from "@/components/site/site-footer";
import { SiteHeader } from "@/components/site/site-header";
import { Standards } from "@/components/site/standards";
import { TriageReplay } from "@/components/site/triage-replay";
import { Why } from "@/components/site/why";
import { evaluation, realData, realLogs, replay, runFacts, type RunFacts } from "@/lib/site-data";
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
      body: (
        <>
          Workers group lines into <Term name="log-template">templates</Term> with Drain,{" "}
          <Term name="pseudonymise">pseudonymise</Term> IP and e-mail addresses with a keyed hash,
          and <Term name="quarantine">quarantine</Term> lines that read like instructions to a
          model. Large inputs fan out across up to 32 workers.
        </>
      ),
      fact: `${f.lines} lines became ${f.templates} templates; ${f.pseudonyms} addresses pseudonymised; ${f.quarantined} line quarantined.`,
      nodes: ["parse1", "parse2", "parse3", "parse4", "merge"],
    },
    {
      title: "Rate severity and recall the past, in parallel",
      body: (
        <>
          Rules and a <Term name="calibrated">calibrated</Term> model score the window. Conformal
          prediction turns the model&apos;s probabilities into a{" "}
          <Term name="prediction-set">set</Term> built to hold the true severity 90% of the time on
          windows like the ones it was calibrated on, and{" "}
          <Term name="safety-floor">safety floors</Term> stop a dangerous pattern being rated too
          low. Meanwhile hybrid search finds similar past incidents.
        </>
      ),
      fact: `${f.severity} at ${Math.round(f.probability * 100)}% probability; ${f.similar} similar past incidents found.`,
      nodes: ["severity", "recall"],
    },
    {
      title: "Investigate with read-only tools",
      body: (
        <>
          An agent proposes hypotheses and tests them through ARIA&apos;s{" "}
          <span className="whitespace-nowrap">
            <Term name="mcp">MCP server</Term>:
          </span>{" "}
          example lines for a template, a component&apos;s timeline, which nodes are affected,
          incident search, runbooks. Every result becomes <Term name="evidence">evidence</Term> a
          claim can cite.
        </>
      ),
      fact: `${f.toolCalls} tool calls; the leading hypothesis is supported at ${Math.round((f.leadingConfidence ?? 0) * 100)}%.`,
      nodes: ["investigate"],
    },
    {
      title: "Check there is enough to go on",
      body: (
        <>
          If no hypothesis holds up or the matches look weak, the graph widens the search and
          investigates again (a <Term name="replan">replan</Term>), at most twice. A quiet window
          with nothing new stops here.
        </>
      ),
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
      body: (
        <>
          The graph pauses and keeps its <Term name="checkpoint">checkpoint</Term>, through restarts
          if need be. A reviewer approves, edits or rejects, and only the messages they approve go
          out.
        </>
      ),
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

/** The real data behind the results, drifting past on the keylime panel. */
const SOURCES = [
  "HDFS, labelled by experts",
  "BlueGene/L alert tags",
  "Thunderbird",
  "Hadoop jobs made to fail",
  "OpenStack fault injection",
  "ServiceNow tickets",
  "GitLab.com incidents",
  "Cloud post-mortems",
  "GAIA labelled logs",
  "Prompt-injection benchmarks",
];

/** The protocols and providers ARIA speaks, as a quiet row of names. */
const SPEAKS = [
  "Model Context Protocol",
  "Agent2Agent",
  "AG-UI",
  "LangGraph",
  "OpenTelemetry",
  "Google Gemini",
  "NVIDIA NIM",
  "Azure OpenAI",
];

const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });

export default function Landing() {
  const data = replay();
  const facts = runFacts();
  const evals = evaluation();
  const real = realLogs();
  const datasets = realData();
  // The HDFS log plus every other real dataset scored on this page.
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
      <main id="main">
        <Hero data={data} />

        <section
          aria-labelledby="speaks-title"
          className="mx-auto max-w-[75rem] px-3 py-14 sm:px-6"
        >
          <h2
            id="speaks-title"
            className="text-center font-sans text-xs font-normal tracking-normal text-muted-foreground"
          >
            Speaks the protocols your tools already use
          </h2>
          <ul className="mt-6 flex flex-wrap items-center justify-center gap-x-10 gap-y-4">
            {SPEAKS.map((name) => (
              <li
                key={name}
                className="text-base font-semibold tracking-[-0.01em] text-charcoal dark:text-foreground"
              >
                {name}
              </li>
            ))}
          </ul>
        </section>

        {/* The problem on the cream page, its lines still apart; the answer on sage, where they
            run together into one. */}
        <section
          aria-labelledby="problem-title"
          className="relative overflow-hidden py-16 lg:py-24"
        >
          <div className="mx-auto grid max-w-[75rem] gap-5 px-3 sm:px-6">
            <span className="tag justify-self-start">The problem</span>
            <h2 id="problem-title" className="text-statement max-w-[36ch]">
              An alert arrives with a wall of logs. The person on call has to read them, judge how
              bad it is and remember what happened last time, often in the middle of the night.
            </h2>
          </div>
          <Converge
            apart
            className="mt-10 w-[110%] -translate-x-[6%] text-heading lg:w-full lg:translate-x-0"
          />
        </section>
        <section
          aria-labelledby="solution-title"
          className="relative overflow-hidden bg-panel-sage py-16 lg:py-24"
        >
          <div className="mx-auto grid max-w-[75rem] gap-5 px-3 sm:px-6">
            <span className="tag justify-self-start bg-raised">The answer</span>
            <h2 id="solution-title" className="text-statement max-w-[36ch]">
              ARIA reads the logs first. It brings back one severity you can check, a report that
              cites its evidence and the incidents that looked like this before, then waits for you
              to approve.
            </h2>
          </div>
          <Converge className="mt-10 w-full text-heading" />
        </section>

        <section
          aria-labelledby="proof-title"
          className="mx-auto grid max-w-[75rem] gap-6 px-3 py-16 sm:px-6 lg:grid-cols-2 lg:gap-12 lg:py-24"
        >
          <ProofTicker items={SOURCES} />
          <div className="grid content-center gap-5">
            <span className="tag justify-self-start">Tested on real data</span>
            <h2 id="proof-title" className="text-statement max-w-[30ch]">
              Measured on public logs, tickets and incidents that their owners labelled, each scored
              against a simpler baseline.
            </h2>
            <dl className="mt-4 flex flex-wrap gap-x-12 gap-y-6">
              <div className="grid gap-1">
                <dt className="order-2 max-w-[18ch] text-xs text-muted-foreground">
                  lines of one supercomputer&apos;s log, scored window by window
                </dt>
                <dd className="stat order-1 text-[3rem]">{compact.format(datasets.bgl.lines)}</dd>
              </div>
              <div className="grid gap-1">
                <dt className="order-2 max-w-[18ch] text-xs text-muted-foreground">
                  real, labelled datasets
                </dt>
                <dd className="stat order-1 text-[3rem]">{nDatasets}</dd>
              </div>
            </dl>
          </div>
        </section>

        <section
          aria-labelledby="why-title"
          className="relative mx-auto max-w-[75rem] px-3 pb-16 sm:px-6 lg:pb-24"
        >
          <Rings className="pointer-events-none absolute -top-10 right-0 w-56 text-heading/40 max-lg:hidden" />
          <div className="mb-10 grid max-w-3xl gap-4">
            <span className="tag justify-self-start">Why ARIA</span>
            <h2 id="why-title" className="text-display">
              A team of agents, working together.
            </h2>
          </div>
          <Why />
        </section>

        <Section
          id="run"
          tone="sage"
          tag="Example run"
          title="One recorded run, start to finish"
          intro={
            <>
              {data.nLines} HDFS log lines (real Loghub lines, arranged into a synthetic incident),
              triaged offline. One line was planted to test the injection guard. Point at a citation
              such as <span className="font-mono text-foreground">E2</span> to see the evidence
              behind a claim.
            </>
          }
        >
          {/* Suspense boundaries let React hydrate each interactive section as its own, shorter
              task, so no single task blocks the main thread for long on a slow phone. */}
          <Suspense>
            <TriageReplay data={data} />
          </Suspense>
        </Section>

        <div className="h-3" />

        <Section
          id="real"
          tone="mint"
          tag="Real logs"
          title="Tested on a real cluster, against its experts"
          intro={
            <>
              {real.lines.toLocaleString("en")} real lines from a Hadoop cluster of more than 200
              nodes, and the label Hadoop experts gave each of its{" "}
              {real.blocks.toLocaleString("en")} storage blocks. ARIA never sees a label, and no
              line in this log is an error: every failure in it is silent.
            </>
          }
        >
          <RealProof data={real} />
          <RealDatasets data={datasets} />
        </Section>

        <Section
          id="how"
          tag="How it works"
          title="What happens in a run"
          intro={
            <>
              A run is a LangGraph state machine with a checkpoint after every step, so it can stop
              for a person, carry on after a restart, or be rewound and{" "}
              <Term name="fork">forked</Term>. The numbers come from the recorded run above. Words
              with a dotted underline open a short definition.
            </>
          }
        >
          <Suspense>
            <RunGraph steps={steps(facts)} />
          </Suspense>
        </Section>

        <Section
          id="results"
          tone="keylime"
          deferred
          tag="Results"
          title="Measured, caveats included"
          intro="These results come from semi-synthetic incidents: real Loghub log lines, composed into incident windows by ARIA's scenario builder, scored against simpler baselines. Every number here comes from the committed evaluation results."
        >
          <Results data={evals} publicAttacks={datasets.injection} />
        </Section>

        <Section
          id="standards"
          deferred
          tag="Standards"
          title="Built on open agent standards"
          intro="ARIA works with the tools you already have, through protocols other agents and frontends speak."
        >
          <Standards />
        </Section>

        <section
          id="faq"
          aria-labelledby="faq-title"
          className="mx-auto max-w-[75rem] px-3 pb-16 sm:px-6 lg:pb-24"
        >
          <Faq />
        </section>

        <Closing />
      </main>
      <SiteFooter recordedAt={data.recordedAt} gitSha={data.gitSha} />
    </>
  );
}
