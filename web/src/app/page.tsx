import { ArrowRightIcon } from "lucide-react";
import Link from "next/link";
import { Suspense, type ReactNode } from "react";

import { resultsInShort } from "@/components/console/test-questions";
import { Closing } from "@/components/site/closing";
import { Explainer } from "@/components/site/explainer";
import { Hero } from "@/components/site/hero";
import { Converge } from "@/components/site/line-art";
import { ResultsRow } from "@/components/site/results-row";
import { SiteFooter } from "@/components/site/site-footer";
import { SiteHeader } from "@/components/site/site-header";
import { StepCarousel } from "@/components/site/step-carousel";
import { stepShowcase } from "@/components/site/step-showcase";
import { TriageReplay } from "@/components/site/triage-replay";
import { WakeApi } from "@/components/site/wake-api";
import { Why } from "@/components/site/why";
import { evaluation, realData, realLogs, replay, type Replay } from "@/lib/site-data";
import { cn } from "@/lib/utils";

// The home page shows ARIA off (owner request, round 9): the headline with a real report, the
// problem and the answer drawn as lines that run together, what it does, the four steps as a
// carousel, one recorded incident to explore, what the tests show, and the way in. Every figure
// comes from the generated data files; the console's How ARIA works pages hold the detail.

type Tone = "keylime" | "slate";

const PANEL: Record<Tone, string> = {
  keylime: "bg-panel-keylime",
  slate: "bg-panel-slate",
};

/** A section: a small tag, the serif heading, a line or two, a link onward and the picture, on
 * the cream page or inside one tinted panel. */
function Section({
  id,
  tag,
  title,
  intro,
  more,
  tone,
  children,
}: {
  id: string;
  tag: string;
  title: ReactNode;
  intro?: ReactNode;
  more?: { href: string; label: string };
  tone?: Tone;
  children: ReactNode;
}) {
  return (
    <section
      id={id}
      aria-labelledby={`${id}-title`}
      className="mx-auto max-w-[75rem] scroll-mt-20 px-3 sm:px-6"
    >
      <div
        className={cn(
          "grid gap-10 lg:gap-12",
          tone
            ? `rounded-card px-5 py-12 sm:px-10 sm:py-16 lg:px-12 ${PANEL[tone]}`
            : "py-16 lg:py-24",
        )}
      >
        <div className="flex flex-wrap items-end justify-between gap-x-10 gap-y-5">
          <div className="grid max-w-3xl gap-4">
            <span className={cn("tag justify-self-start", tone && "bg-raised")}>{tag}</span>
            <h2 id={`${id}-title`} className="text-display">
              {title}
            </h2>
            {intro ? <p className="text-lead max-w-[60ch]">{intro}</p> : null}
          </div>
          {more ? (
            <Link
              href={more.href as never}
              prefetch={false}
              className="inline-flex min-h-6 items-center gap-1.5 text-lg font-medium text-heading underline decoration-control underline-offset-4 hover:decoration-heading"
            >
              {more.label}
              <ArrowRightIcon aria-hidden className="size-5" />
            </Link>
          ) : null}
        </div>
        {children}
      </div>
    </section>
  );
}

/** The problem on the cream page, its lines still apart; the answer on sage, where they run
 * together into one. The lines draw in as each comes into view. */
function ProblemAndAnswer() {
  return (
    <>
      <section
        aria-labelledby="problem-title"
        className="relative overflow-hidden pt-20 pb-14 lg:pt-28 lg:pb-20"
      >
        <div className="mx-auto grid max-w-[75rem] gap-5 px-3 sm:px-6">
          <h2 id="problem-title" className="tag justify-self-start">
            The problem
          </h2>
          <p className="text-display max-w-[22ch] text-heading">
            An alert fires, and a wall of logs comes with it.
          </p>
          <p className="text-lead max-w-[56ch]">
            Someone on call has to read it all, judge how bad it is and remember what happened last
            time, often in the middle of the night.
          </p>
        </div>
        <Converge
          apart
          className="mt-12 h-40 w-[115%] -translate-x-[8%] text-heading sm:h-auto lg:mt-16 lg:w-full lg:translate-x-0"
        />
      </section>
      <section
        aria-labelledby="answer-title"
        className="relative overflow-hidden bg-panel-sage pt-20 pb-14 lg:pt-28 lg:pb-20"
      >
        <div className="mx-auto grid max-w-[75rem] gap-5 px-3 sm:px-6">
          <h2 id="answer-title" className="tag justify-self-start bg-raised">
            The answer
          </h2>
          <p className="text-display max-w-[22ch] text-heading">
            ARIA reads them first, so you start from an answer.
          </p>
          <p className="text-lead max-w-[56ch]">
            It rates how serious the incident is, backs every claim with a log line, finds what
            fixed it last time, and waits for you before anything is sent.
          </p>
        </div>
        <Converge className="mt-12 h-40 w-full text-heading sm:h-auto lg:mt-16" />
      </section>
    </>
  );
}

/** Who did the model's part of the recorded run, in a sentence. */
function writtenBy(data: Replay): string {
  return data.model
    ? `A language model (${data.model.service}) investigated, chose the level from the short list, and wrote the report.`
    : "It ran offline, with no language model.";
}

export default function Landing() {
  const data = replay();
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
        <ProblemAndAnswer />

        <Section
          id="what"
          tag="What it does"
          title="A careful first look at every alert"
          intro="When an alert fires, ARIA has already read the logs. It says how serious the incident is and how sure it is, what changed, what fixed it last time, and drafts the messages for you to approve."
        >
          <Why />
          <Explainer lines={data.fileLines} />
        </Section>

        <Section
          id="how"
          tag="How it works"
          title="Four steps, then you decide"
          more={{ href: "/console/how-it-works/steps", label: "Each step in detail" }}
        >
          <Suspense>
            <StepCarousel data={stepShowcase()} />
          </Suspense>
        </Section>

        <Section
          id="example"
          tone="slate"
          tag="A real example"
          title="One incident, start to finish"
          intro={
            <>
              {data.nLines} real log lines from a Hadoop file system (HDFS), arranged into an
              incident, plus one planted line that tries to trick ARIA. {writtenBy(data)} Point at
              or tap a citation such as <span className="font-mono text-foreground">E2</span> to see
              the lines behind a claim.
            </>
          }
          more={{ href: "/console/how-it-works/example", label: "Open the full example" }}
        >
          {/* Suspense lets React hydrate the interactive replay as its own, shorter task. */}
          <Suspense>
            <TriageReplay data={data} />
          </Suspense>
        </Section>

        <div className="h-6" />

        <Section
          id="results"
          tone="keylime"
          tag="Test results"
          title="Tested on real, labelled logs"
          intro={`ARIA is tested on ${nDatasets} public, labelled datasets, each against a simpler method.`}
          more={{ href: "/console/evals", label: "See every test" }}
        >
          <p className="max-w-[62ch] text-xl leading-relaxed font-medium text-heading">
            {resultsInShort(evals, real)}
          </p>
          <ResultsRow data={evals} real={real} />
        </Section>

        <div className="h-6" />

        <Closing />
      </main>
      <SiteFooter recordedAt={data.recordedAt} />
    </>
  );
}
