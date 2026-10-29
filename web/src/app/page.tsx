import { ArrowDownIcon } from "lucide-react";
import Link from "next/link";

import { Orb } from "@/components/aria/orb";
import { Term } from "@/components/aria/term";
import { Results } from "@/components/site/results";
import { RunGraph, type GraphStep } from "@/components/site/run-graph";
import { SiteFooter } from "@/components/site/site-footer";
import { SiteHeader } from "@/components/site/site-header";
import { Limitations, Standards } from "@/components/site/standards";
import { TriageReplay } from "@/components/site/triage-replay";
import { Button } from "@/components/ui/button";
import { evaluation, REPO_URL, replay, runFacts, type RunFacts } from "@/lib/site-data";
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
          <Term name="prediction-set">set</Term> that holds the true severity 90% of the time, and{" "}
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
          <Term name="mcp">MCP server</Term>: example lines for a template, a component&apos;s
          timeline, which nodes are affected, incident search, runbooks. Every result becomes{" "}
          <Term name="evidence">evidence</Term> a claim can cite.
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

function Section({
  id,
  label,
  title,
  intro,
  deferred = false,
  children,
}: {
  id: string;
  /** The section's name, as the navigation calls it. */
  label: string;
  title: string;
  intro?: React.ReactNode;
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
        "scroll-mt-4",
        deferred && "[contain-intrinsic-size:auto_1400px] [content-visibility:auto]",
      )}
    >
      <div className="mx-auto grid max-w-[90rem] gap-12 px-4 py-20 sm:px-6 lg:px-8 lg:py-28">
        <div className="grid max-w-5xl gap-5">
          <p className="eyebrow text-muted-foreground">{label}</p>
          <h2
            id={`${id}-title`}
            className="text-4xl leading-none tracking-heading sm:text-5xl sm:tracking-display"
          >
            {title}
          </h2>
          {intro ? <p className="max-w-3xl text-lg text-muted-foreground">{intro}</p> : null}
        </div>
        {children}
      </div>
    </section>
  );
}

function Hero() {
  return (
    <section aria-labelledby="hero-title" className="relative isolate -mt-20 overflow-hidden">
      <Orb className="absolute top-0 left-1/2 -z-10 aspect-square w-[min(46rem,140vw)] -translate-x-1/2 [mask-image:linear-gradient(to_bottom,#000_36%,transparent_64%)]" />
      <div className="mx-auto grid max-w-[90rem] justify-items-center gap-7 px-4 pt-[min(68vw,24rem)] pb-20 text-center sm:px-6 sm:pt-[min(52vw,28rem)] lg:px-8 lg:pb-28">
        <p className="eyebrow text-muted-foreground">Open-source incident triage</p>
        <h1
          id="hero-title"
          className="max-w-[11ch] text-[2.75rem] leading-none tracking-display sm:text-6xl lg:max-w-[12ch] lg:text-[5.375rem] lg:tracking-[-0.046em]"
        >
          Incident triage that shows its work.
        </h1>
        <p className="max-w-2xl text-lg text-muted-foreground">
          ARIA reads an alert and its logs, rates severity with calibrated confidence, checks what
          happened last time and drafts the incident report. Every claim cites its evidence, and
          nothing is sent until a person approves.
        </p>
        <div className="flex flex-wrap justify-center gap-3">
          <Button asChild variant="primary" size="lg">
            <Link href="/console" prefetch={false}>
              Open the console
            </Link>
          </Button>
          <Button asChild variant="ghost" size="lg">
            <a href="#run">
              Watch a real run
              <ArrowDownIcon aria-hidden />
            </a>
          </Button>
        </div>
      </div>
    </section>
  );
}

// The README's offline quick start, without keys.
const QUICKSTART = ["make install", "uv run aria db upgrade && uv run aria seed", "make dev"];

function TryIt() {
  return (
    <section aria-labelledby="try-title" className="px-4 pb-20 sm:px-6 lg:px-8 lg:pb-28">
      <div className="mx-auto grid max-w-[90rem] justify-items-center gap-6 rounded-lg bg-raised px-6 py-16 text-center sm:px-12 lg:py-20">
        <p className="eyebrow text-muted-foreground">Try it</p>
        <h2 id="try-title" className="max-w-2xl text-4xl leading-none tracking-display sm:text-5xl">
          Run ARIA on your own logs
        </h2>
        <p className="max-w-2xl text-lg text-muted-foreground">
          It runs offline with no API key, and switches to NVIDIA NIM, Azure OpenAI or any
          OpenAI-compatible model when you add one. The console walks you through a first triage.
        </p>
        <pre className="w-full max-w-xl overflow-x-auto rounded-lg bg-sunken px-5 py-4 text-left text-sm leading-relaxed text-foreground">
          <code>
            {QUICKSTART.map((command) => (
              <span key={command} className="block">
                <span aria-hidden className="text-faint select-none">
                  ${" "}
                </span>
                {command}
              </span>
            ))}
          </code>
        </pre>
        <div className="flex flex-wrap justify-center gap-3">
          <Button asChild variant="secondary" size="lg">
            <Link href="/console" prefetch={false}>
              Open the console
            </Link>
          </Button>
          <Button asChild variant="ghost" size="lg">
            <a href={`${REPO_URL}#quickstart`}>Read the quick start</a>
          </Button>
        </div>
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
        <Hero />

        <Section
          id="run"
          label="Example run"
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
          <TriageReplay data={data} />
        </Section>

        <Section
          id="how"
          label="How it works"
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
          <RunGraph steps={steps(facts)} />
        </Section>

        <Section
          id="results"
          deferred
          label="Results"
          title="Measured, caveats included"
          intro="ARIA is tested on incident windows built from real Loghub logs, against simpler baselines. Every number on this page comes from the committed evaluation results."
        >
          <Results data={evals} />
        </Section>

        <Section
          id="standards"
          deferred
          label="Standards"
          title="Built on open agent standards"
          intro="ARIA works with the tools you already have, through protocols other agents and frontends speak."
        >
          <Standards />
        </Section>

        <Section id="limits" label="Limits" title="Where it falls short" deferred>
          <Limitations />
        </Section>

        <TryIt />
      </main>
      <SiteFooter recordedAt={data.recordedAt} gitSha={data.gitSha} />
    </>
  );
}
