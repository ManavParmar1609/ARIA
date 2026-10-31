import { Suspense, type ReactNode } from "react";

import { Term } from "@/components/aria/term";
import { resultsInShort } from "@/components/console/test-questions";
import { Explainer } from "@/components/site/explainer";
import { Faq } from "@/components/site/faq";
import { ResultsRow } from "@/components/site/results-row";
import { RunGraph, type GraphStep } from "@/components/site/run-graph";
import { TriageReplay } from "@/components/site/triage-replay";
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

// How ARIA works, told in five short parts: what it does, one recorded incident, the four steps,
// what the tests show and the questions people ask. Each part is a page of the console's How ARIA
// works section; the home page keeps only the headline, the proof and a line per step (owner
// feedback, round 8).

/** How a run works, in four steps (item 28), each with what happened in the recorded run. */
function steps(f: RunFacts, target: number): GraphStep[] {
  return [
    {
      title: "Read the logs",
      body: (
        <>
          ARIA groups similar lines into patterns (<Term name="log-template">templates</Term>),
          hides IP and e-mail addresses behind stand-in names, and sets aside any line that tries to
          give it orders (it is <Term name="quarantine">quarantined</Term>).
        </>
      ),
      fact: `${f.lines} lines became ${f.templates} templates; ${f.pseudonyms} addresses replaced; ${f.quarantined} planted line set aside.`,
      nodes: ["plan", "parse1", "parse2", "parse3", "parse4", "merge"],
    },
    {
      title: "Rate how serious it is, and recall the past",
      body: (
        <>
          Rules and a trained model score the logs and keep a{" "}
          <Term name="prediction-set">short list</Term> of likely levels, built to hold the right
          one {Math.round(target * 100)} times in 100. A dangerous pattern is never rated too low.
          At the same time, ARIA looks for similar past incidents.
        </>
      ),
      fact: `${f.severity} at ${Math.round(f.probability * 100)}% probability; ${f.similar} similar past incidents found.`,
      nodes: ["severity", "recall"],
    },
    {
      title: "Investigate and write the report",
      body: (
        <>
          ARIA tests its ideas about the cause with tools that can only read: example lines, a
          part&apos;s timeline, past incidents and <Term name="runbook">runbooks</Term>. Each result
          becomes <Term name="evidence">evidence</Term>, and the report may only say what the
          evidence shows. If the evidence is thin, ARIA looks further, at most twice.
        </>
      ),
      fact: `${f.toolCalls} tool calls; ${f.claims} claims checked, ${Math.round(f.citationCoverage * 100)}% cited; ${f.actions} messages drafted.`,
      nodes: ["investigate", "assess", "report", "comms"],
    },
    {
      title: "Wait for a person, then remember",
      body: (
        <>
          The run pauses for you. You approve, edit or discard the messages, and only what you
          approve is sent. The approved incident joins ARIA&apos;s memory, so the next similar alert
          finds it.
        </>
      ),
      fact: `Ready for review ${(f.timeToReviewMs / 1000).toFixed(1)} s after the logs arrived.`,
      nodes: ["review", "publish"],
    },
  ];
}

/** Who did the model's part of the recorded run, in a sentence. */
function writtenBy(data: Replay): string {
  return data.model
    ? `A language model (${data.model.service}) investigated, chose the level from the short list, and wrote the report and the messages.`
    : "It ran offline, with no language model.";
}

/** One part of How ARIA works: a heading, a line or two, then the picture. */
function Part({
  id,
  title,
  intro,
  tinted = false,
  children,
}: {
  id: string;
  title: string;
  intro?: ReactNode;
  tinted?: boolean;
  children: ReactNode;
}) {
  return (
    <section
      aria-labelledby={`${id}-title`}
      className={cn("grid gap-6", tinted && "rounded-card bg-panel-sage p-5 sm:p-8")}
    >
      <div className="grid max-w-3xl gap-2">
        <h2 id={`${id}-title`} className="text-section">
          {title}
        </h2>
        {intro ? <p className="text-lead max-w-[62ch]">{intro}</p> : null}
      </div>
      {children}
    </section>
  );
}

/** Part 1: what ARIA does for the person on call, and the explainer video. */
export function WhatItDoesPart() {
  const data = replay();
  return (
    <Part
      id="what-it-does"
      title="What ARIA does for the person on call"
      intro="When an alert fires, ARIA has already read the logs. It says how serious the incident is and how sure it is, what changed, what fixed it last time, and drafts the messages for you to approve."
    >
      <Why />
      <Explainer lines={data.fileLines} />
    </Part>
  );
}

/** Part 2: one recorded incident, with every claim's evidence a point or a tap away. */
export function ExamplePart() {
  const data = replay();
  return (
    <Part
      id="example"
      tinted
      title="One incident, start to finish"
      intro={
        <>
          {data.nLines} real HDFS log lines from Loghub, arranged into an incident, plus one planted
          line that tries to trick ARIA. {writtenBy(data)} Point at or tap a citation such as{" "}
          <span className="font-mono text-foreground">E2</span> to see the lines behind a claim.
        </>
      }
    >
      {/* Suspense lets React hydrate the interactive replay as its own, shorter task. */}
      <Suspense>
        <TriageReplay data={data} />
      </Suspense>
    </Part>
  );
}

/** Part 3: the four steps, with what each did in the recorded incident. */
export function StepsPart() {
  return (
    <Part
      id="steps"
      title="Four steps, then a person decides"
      intro="What ARIA does with an alert's logs, step by step. The figures come from the recorded example, and words with a dotted underline open a short definition."
    >
      <Suspense>
        <RunGraph steps={steps(runFacts(), evaluation().severity.targetCoverage)} />
      </Suspense>
    </Part>
  );
}

/** Part 4: four findings from the tests, one where ARIA falls short, led by what they mean for
 * the person on call, so a figure such as "the best standard detector did the same" reads as the
 * match it is. */
export function ResultsPart() {
  const datasets = realData();
  const data = evaluation();
  const real = realLogs();
  // The HDFS log plus every other real dataset on Test results.
  const nDatasets = Object.keys(datasets).length + 1;
  return (
    <Part
      id="results"
      tinted
      title="What the tests show"
      intro={`ARIA is tested on ${nDatasets} public, labelled datasets, each against a simpler method. The four findings below include one where it falls short.`}
    >
      <p className="max-w-[62ch] text-lg leading-relaxed font-medium text-heading">
        {resultsInShort(data, real, datasets)}
      </p>
      <ResultsRow data={data} real={real} more={datasets} />
    </Part>
  );
}

/** Part 5: the questions people ask first, and where ARIA falls short. */
export function QuestionsPart() {
  return <Faq />;
}
