import { ArrowDownIcon } from "lucide-react";
import Link from "next/link";
import { Suspense, type ReactNode } from "react";

import { Term } from "@/components/aria/term";
import { HeroScene, HillsBand } from "@/components/illustrations/scenes";
import { Results } from "@/components/site/results";
import { RunGraph, type GraphStep } from "@/components/site/run-graph";
import { SiteFooter } from "@/components/site/site-footer";
import { SiteHeader } from "@/components/site/site-header";
import { Limitations, Standards } from "@/components/site/standards";
import { Story } from "@/components/site/story";
import { TriageReplay } from "@/components/site/triage-replay";
import { ArrowCircle, Button } from "@/components/ui/button";
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

type Dot = "coral" | "sunshine" | "sky" | "lilac";

const DOT: Record<Dot, string> = {
  coral: "bg-coral",
  sunshine: "bg-sunshine",
  sky: "bg-sky",
  lilac: "bg-lilac",
};

function Section({
  id,
  label,
  dot,
  title,
  intro,
  deferred = false,
  children,
}: {
  id: string;
  /** The section's name, as the navigation calls it. */
  label: string;
  /** The small chromatic dot beside the name: one pop colour per section. */
  dot: Dot;
  title: ReactNode;
  intro?: ReactNode;
  /** Skip layout and paint until the section nears the viewport (for sections far below the
   * fold that nothing measures on load). */
  deferred?: boolean;
  children: ReactNode;
}) {
  return (
    <section
      id={id}
      aria-labelledby={`${id}-title`}
      className={cn(
        "scroll-mt-20",
        deferred && "[contain-intrinsic-size:auto_1400px] [content-visibility:auto]",
      )}
    >
      <div className="mx-auto grid max-w-[75rem] gap-12 px-4 py-20 sm:px-6 lg:gap-16 lg:py-28">
        <div className="grid max-w-4xl gap-5">
          <p className="eyebrow inline-flex items-center gap-2.5 text-muted-foreground">
            <span aria-hidden className={cn("block size-2.5 rounded-full", DOT[dot])} />
            {label}
          </p>
          <h2
            id={`${id}-title`}
            className="text-[2.5rem] leading-none tracking-heading sm:text-4xl lg:text-6xl lg:leading-[0.98]"
          >
            {title}
          </h2>
          {intro ? (
            <p className="max-w-3xl text-lg text-muted-foreground sm:text-xl">{intro}</p>
          ) : null}
        </div>
        {children}
      </div>
    </section>
  );
}

/** A hand-drawn lilac underline under one word of a heading, as in the reference. */
function Scribble({ children }: { children: ReactNode }) {
  return (
    <span className="relative whitespace-nowrap">
      {children}
      <svg
        aria-hidden
        focusable="false"
        viewBox="0 0 200 16"
        preserveAspectRatio="none"
        className="absolute -bottom-[0.12em] left-0 h-[0.16em] w-full"
      >
        <path
          d="M3 9C22 2 30 15 50 8S80 2 100 9S132 15 150 8S182 2 197 8"
          fill="none"
          stroke="var(--lilac)"
          strokeWidth="5"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
    </span>
  );
}

function Hero() {
  return (
    <section
      aria-labelledby="hero-title"
      className="relative overflow-hidden bg-grass pt-28 text-pop-ink sm:pt-36 lg:pt-40"
    >
      <div className="mx-auto grid max-w-[75rem] justify-items-center gap-6 px-4 text-center sm:px-6">
        <h1 id="hero-title" className="text-display max-w-[13ch] text-pop-ink">
          Incident triage that shows its work.
        </h1>
        <p className="text-lead max-w-[30ch]">
          Calibrated severity, a report that cites every claim, and nothing sent until a person
          approves.
        </p>
        <div className="mt-2 flex flex-wrap justify-center gap-3">
          <Button asChild variant="raised" size="lg" className="pr-2">
            <Link href="/console" prefetch={false}>
              Open the console
              <ArrowCircle />
            </Link>
          </Button>
          <Button
            asChild
            variant="ghost"
            size="lg"
            className="text-pop-ink hover:bg-pop-ink/8 hover:text-pop-ink"
          >
            <a href="#run">
              Watch a real run
              <ArrowDownIcon aria-hidden />
            </a>
          </Button>
        </div>
      </div>
      <HeroScene className="mx-auto mt-6 block h-[19rem] w-full max-w-[72rem] sm:h-auto sm:px-2" />
    </section>
  );
}

function Intro() {
  return (
    <section
      aria-labelledby="story-title"
      className="mx-auto max-w-[75rem] px-4 pt-20 pb-6 sm:px-6 lg:pt-28"
    >
      <h2 id="story-title" className="sr-only">
        What ARIA does
      </h2>
      <p className="text-lead max-w-[38ch]">
        ARIA reads an alert and its logs, rates severity with calibrated confidence, checks what
        happened last time and drafts the incident report, so the person on call starts from
        evidence instead of a wall of logs.
      </p>
      <Button asChild variant="raised" size="lg" className="mt-8 pr-2">
        <a href="#how">
          How a run works
          <ArrowCircle />
        </a>
      </Button>
      <div className="mt-16 lg:mt-20">
        <Story />
      </div>
    </section>
  );
}

// The README's offline quick start, without keys.
const QUICKSTART = ["make install", "uv run aria db upgrade && uv run aria seed", "make dev"];

const PROMISES = [
  "Runs offline, with no API key",
  "Every claim cites its evidence",
  "Nothing is sent without approval",
];

function TryIt() {
  return (
    <section aria-labelledby="try-title" className="relative z-10">
      <HillsBand className="block h-32 w-full sm:h-44 lg:h-52" />
      <div className="-mt-px rounded-b-sheet bg-grass text-pop-ink">
        <div className="mx-auto grid max-w-[75rem] justify-items-center gap-8 px-4 pt-6 pb-24 text-center sm:px-6 lg:pb-28">
          <h2 id="try-title" className="text-display max-w-[11ch] text-pop-ink">
            Run it on your own logs.
          </h2>
          <p className="text-lead max-w-[36ch]">
            ARIA runs offline with no API key, and switches to NVIDIA NIM, Azure OpenAI or any
            OpenAI-compatible model when you add one.
          </p>
          {/* Long commands wrap (with a hanging indent) rather than scroll, so phones need no
              sideways scrolling inside the block. */}
          <pre className="w-full max-w-xl rounded-lg bg-raised px-5 py-4 text-left text-sm leading-relaxed whitespace-pre-wrap text-foreground">
            <code>
              {QUICKSTART.map((command) => (
                <span key={command} className="block pl-[2ch] -indent-[2ch]">
                  <span aria-hidden className="text-faint select-none">
                    ${" "}
                  </span>
                  {command}
                </span>
              ))}
            </code>
          </pre>
          <div className="flex flex-wrap justify-center gap-3">
            <Button asChild variant="raised" size="lg" className="pr-2">
              <Link href="/console" prefetch={false}>
                Open the console
                <ArrowCircle />
              </Link>
            </Button>
            <Button
              asChild
              variant="ghost"
              size="lg"
              className="text-pop-ink hover:bg-pop-ink/8 hover:text-pop-ink"
            >
              <a href={`${REPO_URL}#quickstart`}>Read the quick start</a>
            </Button>
          </div>
          <ul className="mt-10 grid w-full gap-4 text-lg sm:grid-cols-3">
            {PROMISES.map((promise) => (
              <li key={promise}>{promise}</li>
            ))}
          </ul>
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

        {/* The cream page laid over the green hero, its top corners rounded like a sheet. */}
        <div className="relative z-10 -mt-[50px] rounded-t-sheet bg-background">
          <Intro />

          <Section
            id="run"
            label="Example run"
            dot="coral"
            title="One recorded run, start to finish"
            intro={
              <>
                {data.nLines} HDFS log lines (real Loghub lines, arranged into a synthetic
                incident), triaged offline. One line was planted to test the injection guard. Point
                at a citation such as <span className="font-mono text-foreground">E2</span> to see
                the evidence behind a claim.
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
            label="How it works"
            dot="sky"
            title="What happens in a run"
            intro={
              <>
                A run is a LangGraph state machine with a checkpoint after every step, so it can
                stop for a person, carry on after a restart, or be rewound and{" "}
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
            deferred
            label="Results"
            dot="lilac"
            title={
              <>
                <Scribble>Measured,</Scribble> caveats included
              </>
            }
            intro="ARIA is tested on incident windows built from real Loghub logs, against simpler baselines. Every number on this page comes from the committed evaluation results."
          >
            <Results data={evals} />
          </Section>

          <Section
            id="standards"
            deferred
            label="Standards"
            dot="sunshine"
            title="Built on open agent standards"
            intro="ARIA works with the tools you already have, through protocols other agents and frontends speak."
          >
            <Standards />
          </Section>

          <Section id="limits" label="Limits" dot="coral" title="Where it falls short" deferred>
            <Limitations />
          </Section>
        </div>

        <TryIt />
      </main>
      <SiteFooter recordedAt={data.recordedAt} gitSha={data.gitSha} />
    </>
  );
}
