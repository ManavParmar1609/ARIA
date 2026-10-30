"use client";

import { ArrowRightIcon, LoaderCircleIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorState, PageHeader } from "@/components/console/states";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import samples from "@/data/samples.json";
import { type RealIncident, useCreateRun, useRealIncidents, useReplay } from "@/lib/api/hooks";
import { GLOSSARY } from "@/lib/glossary";
import { systemName } from "@/lib/systems";

// What each sample shows a newcomer. Outcomes are not promised here: with a model configured
// the result can differ, and the run view explains whatever ARIA decided.
const SAMPLE_NOTES: Record<string, string> = {
  "hdfs.block_serve_exceptions":
    "Storage nodes failing to hand out data blocks. Memory holds a similar past incident.",
  "openssh.bruteforce": "Repeated failed logins from many addresses: a security pattern.",
  "zookeeper.quorum_connection_loss":
    "Coordination servers losing touch with each other: a classic outage.",
  "mac.cocoa_scripting_noise":
    "Mostly harmless noise: a good test of how ARIA behaves when it is unsure.",
};

const READING = [
  {
    title: "The header",
    body: "The severity strip and the title ARIA wrote, where the logs came from, how long the report took, whether a model was used and how many tools the investigator called.",
  },
  {
    title: "The steps",
    body: "The run's progress through the graph, with each step's time. Review is the step that waits for you.",
  },
  {
    title: "Severity",
    body: "Bars show the calibrated probability of each severity, and the bracket marks the prediction set. The text says who decided: the rules, the model, a model choosing within the set, or, when ARIA is unsure, the most severe severity in the set, flagged for you to check. Open the rule trace to see which rules fired.",
  },
  {
    title: "The report",
    body: "A summary, the suspected cause, a timeline and next steps. Every claim carries evidence IDs such as E3: point at one to see what it rests on, or click it to pin it in the evidence panel.",
  },
  {
    title: "Review",
    body: "Approve and publish, edit first, or reject. Tick the messages you want sent; anything left unticked stays a draft.",
  },
  {
    title: "The tabs below",
    body: "How the agents worked tells the run as each agent's turn: what it found and why it concluded what it did. The event log lists every step and tool call. Evidence lists everything the report may cite. Logs shows the templates ARIA mined. History lets you rewind to any checkpoint, or fork a new run with different options.",
  },
];

const SOURCES = [
  {
    title: "Alerts",
    body: "Alertmanager, Grafana and generic webhooks. Alerts that fire together become one run, not a storm of runs.",
  },
  {
    title: "The log scan",
    body: "A periodic scan of a log folder opens a run when errors burst above their usual rate.",
  },
  {
    title: "People",
    body: "Paste logs on the New triage page, or run aria triage on a file from the command line.",
  },
  {
    title: "Other agents",
    body: "Through A2A and AG-UI. Any MCP client can also search ARIA's memory with its read-only tools.",
  },
];

// Each sample card's button takes one of the pops, as the site's story cards do.

function SampleCard({ sample }: { sample: (typeof samples)[number] }) {
  const router = useRouter();
  const create = useCreateRun();
  const [started, setStarted] = useState(false);
  const busy = create.isPending || started;
  const start = () => {
    create.mutate(
      {
        system: sample.system,
        logs: sample.lines,
        synthetic: true,
        options: { use_llm: true, investigate: true, require_approval: true },
      },
      {
        onSuccess: (accepted) => {
          setStarted(true);
          toast.success("Triage started", { description: "Following the run live." });
          router.push(`/console/runs/${encodeURIComponent(accepted.run_id)}` as never);
        },
      },
    );
  };
  return (
    <li className="flex flex-col gap-3 rounded-lg bg-raised p-5 sm:p-6">
      <p className="eyebrow text-muted-foreground">
        {systemName(sample.system)}, {sample.lines.length} lines
      </p>
      <h3 className="text-lg leading-snug tracking-heading">{sample.label}</h3>
      <p className="text-sm text-muted-foreground">{SAMPLE_NOTES[sample.id]}</p>
      <Button
        variant="primary"
        size="md"
        className="mt-auto self-start"
        onClick={start}
        disabled={busy}
        // The visible words lead the name (WCAG 2.5.3), and the sample tells the four apart.
        aria-label={`${busy ? "Starting" : "Triage it"}: ${sample.label}`}
      >
        {busy ? "Starting" : "Triage it"}
        {busy ? <LoaderCircleIcon aria-hidden className="size-4 animate-spin" /> : null}
      </Button>
      {create.isError ? (
        <ErrorState error={create.error} title="The sample could not be started" />
      ) : null}
    </li>
  );
}

function RealFact({ value, label }: { value: number; label: string }) {
  return (
    <div className="grid gap-1">
      <dt className="order-2 text-sm text-muted-foreground">{label}</dt>
      <dd className="stat order-1 text-3xl">{value.toLocaleString("en")}</dd>
    </div>
  );
}

function RealIncidentCard({ incident }: { incident: RealIncident }) {
  const router = useRouter();
  const replay = useReplay();
  const [started, setStarted] = useState(false);
  const busy = replay.isPending || started;
  const start = () => {
    replay.mutate(
      {
        id: incident.id,
        body: { options: { use_llm: true, investigate: true, require_approval: true } },
      },
      {
        onSuccess: (accepted) => {
          setStarted(true);
          toast.success("Replay started", { description: "Following the run live." });
          router.push(`/console/runs/${encodeURIComponent(accepted.run_id)}` as never);
        },
      },
    );
  };
  return (
    <li className="grid gap-6 rounded-lg bg-raised p-5 sm:p-8 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end lg:gap-10">
      <div className="grid gap-4">
        <p className="eyebrow flex items-center gap-2 text-muted-foreground">
          <span aria-hidden className="size-2 rounded-full bg-primary" />
          {systemName(incident.system)}, real logs
        </p>
        <h3 className="text-2xl leading-tight tracking-heading sm:text-3xl">{incident.title}</h3>
        <p className="max-w-2xl text-muted-foreground">{incident.summary}</p>
        <dl className="flex flex-wrap gap-x-10 gap-y-4">
          <RealFact value={incident.lines} label="real log lines" />
          <RealFact value={incident.units} label={`${incident.unit}s in the log`} />
          <RealFact value={incident.labelled_failures} label="labelled failed by its experts" />
        </dl>
        <p className="text-xs text-faint">
          {incident.source}. Labels: {incident.citation}
        </p>
      </div>
      <div className="grid gap-3 lg:justify-items-end">
        <Button
          variant="primary"
          size="lg"
          className="justify-self-start lg:justify-self-end"
          onClick={start}
          disabled={busy}
          aria-label={`${busy ? "Starting" : "Replay it"}: ${incident.title}`}
        >
          {busy ? "Starting" : "Replay it"}
          {busy ? <LoaderCircleIcon aria-hidden className="size-5 animate-spin" /> : null}
        </Button>
        {replay.isError ? (
          <ErrorState error={replay.error} title="The replay could not be started" />
        ) : null}
      </div>
    </li>
  );
}

function RealIncidents() {
  const incidents = useRealIncidents();
  return (
    <section aria-labelledby="real-title" className="grid gap-5">
      <div className="grid gap-2">
        <h2 id="real-title" className="text-xl tracking-heading">
          Replay a real incident
        </h2>
        <p className="max-w-3xl text-muted-foreground">
          Real lines from a real system&rsquo;s log, with the label its experts gave every unit of
          work. ARIA never sees the labels: the run page puts them next to what ARIA found.
        </p>
      </div>
      {incidents.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : incidents.isError ? (
        <ErrorState
          error={incidents.error}
          title="The real incidents could not be listed"
          onRetry={() => void incidents.refetch()}
        />
      ) : incidents.data.length ? (
        <ul className="grid gap-4">
          {incidents.data.map((incident) => (
            <RealIncidentCard key={incident.id} incident={incident} />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">
          This server ships no real incidents to replay. The samples below still run.
        </p>
      )}
    </section>
  );
}

/** The console's front door for a first visit: try a sample, learn to read a run, look up a word. */
export function Guide() {
  return (
    <div className="grid gap-14">
      <PageHeader
        eyebrow="Start here"
        title="How to use ARIA"
        description="ARIA reads an alert and its logs, rates severity, checks what happened last time and drafts a cited report that waits for your approval. The quickest way in is a real incident or a sample: each runs in seconds, and nothing is sent anywhere."
      />

      <RealIncidents />

      <section aria-labelledby="samples-title" className="grid gap-5">
        <div className="grid gap-2">
          <h2 id="samples-title" className="text-xl tracking-heading">
            Triage a sample
          </h2>
          <p className="max-w-3xl text-muted-foreground">
            Each sample is real Loghub log lines arranged into a synthetic incident. One click
            starts the run and opens it, so you can watch each step happen.
          </p>
        </div>
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {samples.map((sample) => (
            <SampleCard key={sample.id} sample={sample} />
          ))}
        </ul>
      </section>

      <section aria-labelledby="read-title" id="read-a-run" className="grid scroll-mt-6 gap-5">
        <div className="grid gap-2">
          <h2 id="read-title" className="text-xl tracking-heading">
            How to read a run
          </h2>
          <p className="max-w-3xl text-muted-foreground">
            A run page reads from top to bottom, in the order ARIA did the work.
          </p>
        </div>
        <ol className="grid gap-x-8 gap-y-6 md:grid-cols-2">
          {READING.map((part, i) => (
            <li key={part.title} className="grid grid-cols-[2.25rem_1fr] gap-x-3">
              <span
                aria-hidden
                className="tabular flex size-8 items-center justify-center rounded-full bg-raised text-sm font-medium text-primary"
              >
                {i + 1}
              </span>
              <div className="grid content-start gap-1">
                <h3 className="text-base font-medium">{part.title}</h3>
                <p className="text-sm text-muted-foreground">{part.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="words-title" id="words" className="grid scroll-mt-6 gap-5">
        <div className="grid gap-2">
          <h2 id="words-title" className="text-xl tracking-heading">
            Words ARIA uses
          </h2>
          <p className="max-w-3xl text-muted-foreground">
            The same definitions open from any word with a dotted underline on the landing page.
          </p>
        </div>
        <dl className="grid gap-x-10 rounded-lg bg-sunken px-5 py-2 sm:px-8 md:grid-cols-2">
          {Object.values(GLOSSARY).map((entry) => (
            <div
              key={entry.term}
              className="grid content-start gap-1 border-b border-rule py-5 last:border-b-0 md:[&:nth-last-child(-n+2)]:border-b-0"
            >
              <dt className="font-medium text-heading">{entry.term}</dt>
              <dd className="text-sm text-muted-foreground">{entry.definition}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section aria-labelledby="sources-title" className="grid gap-5">
        <div className="grid gap-2">
          <h2 id="sources-title" className="text-xl tracking-heading">
            Where runs come from
          </h2>
          <p className="max-w-3xl text-muted-foreground">
            In production most runs start on their own. The New triage page shows how to connect
            each source.
          </p>
        </div>
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {SOURCES.map((source) => (
            <li key={source.title} className="grid content-start gap-2 rounded-lg bg-raised p-5">
              <h3 className="text-base font-medium">{source.title}</h3>
              <p className="text-sm text-muted-foreground">{source.body}</p>
            </li>
          ))}
        </ul>
        <Button asChild variant="ghost" className="justify-self-start">
          <Link href="/console/runs/new">
            Connect a source or paste logs
            <ArrowRightIcon aria-hidden />
          </Link>
        </Button>
      </section>
    </div>
  );
}
