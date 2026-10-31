"use client";

import { ArrowLeftIcon, ArrowRightIcon, LoaderCircleIcon, PlayIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { OnThisPage, type TocItem } from "@/components/console/on-this-page";
import { PageHeader, SectionHeader } from "@/components/console/states";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import { useScenarios, useStartSample } from "@/lib/api/hooks";
import { GLOSSARY } from "@/lib/glossary";

// The guide, arranged by what a newcomer wants to do (item 26): five short tasks, each with its
// way in beside it, then the words ARIA uses. The samples live on New triage and the incident page
// explains itself where it matters, so neither is repeated here, and nothing starts on its own.

/** The sample the first task starts: a clear, quick incident with a security response. */
const FIRST_SAMPLE = "openssh.bruteforce";

function StartSample() {
  const router = useRouter();
  const card = useScenarios().data?.find((s) => s.id === FIRST_SAMPLE);
  const start = useStartSample();
  const starting = useRef(false);
  const [started, setStarted] = useState(false);
  const busy = start.isPending || started;
  const title = card?.title ?? "a sample";
  const run = () => {
    // A double click would start two runs before the first one's state reached the button.
    if (!card || starting.current) return;
    starting.current = true;
    start.mutate(
      {
        id: card.id,
        body: {
          servers: null,
          rate: null,
          options: { use_llm: true, investigate: true, require_approval: true },
        },
      },
      {
        onSuccess: (accepted) => {
          setStarted(true);
          router.push(`/console/runs/${encodeURIComponent(accepted.run_id)}` as never);
        },
        onError: (error) => {
          starting.current = false;
          toast.error("The sample could not be started", {
            description: error instanceof ApiError ? error.detail : String(error),
          });
        },
      },
    );
  };
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <Button
        variant="primary"
        onClick={run}
        disabled={!card || busy}
        // The visible words lead the name (WCAG 2.5.3), and the sample's title follows them.
        aria-label={`${busy ? "Starting" : "Triage a sample"}: ${title}`}
      >
        {busy ? (
          <LoaderCircleIcon aria-hidden className="size-4 animate-spin" />
        ) : (
          <PlayIcon aria-hidden />
        )}
        {busy ? "Starting" : "Triage a sample"}
      </Button>
      <Link
        href="/console/runs/new"
        className="text-sm underline decoration-control underline-offset-4 hover:text-heading"
      >
        Or choose one on New triage
      </Link>
    </div>
  );
}

function Task({
  id,
  number,
  title,
  children,
  action,
}: {
  id: string;
  number: number;
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <li
      id={id}
      className="grid scroll-mt-24 grid-cols-[2.75rem_minmax(0,1fr)] gap-x-4 rounded-card border border-rule bg-raised p-5 sm:p-6 lg:scroll-mt-8"
    >
      <span
        aria-hidden
        className="tabular grid size-11 place-items-center rounded-full bg-panel-keylime text-lg font-semibold text-heading"
      >
        {number}
      </span>
      <div className="grid content-start gap-3">
        <h3 className="text-xl leading-snug">{title}</h3>
        <div className="grid max-w-prose gap-2 text-base leading-relaxed text-foreground">
          {children}
        </div>
        {action ? <div className="pt-1">{action}</div> : null}
      </div>
    </li>
  );
}

function TaskLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link
      href={href as never}
      className="inline-flex items-center gap-1.5 text-sm font-medium underline decoration-control underline-offset-4 hover:text-heading"
    >
      {children}
      <ArrowRightIcon aria-hidden className="size-4" />
    </Link>
  );
}

// The guide's sections, for its "On this page" list.
const CONTENTS: TocItem[] = [
  {
    id: "tasks",
    label: "Five things to try",
    children: [
      { id: "first-incident", label: "Triage your first incident" },
      { id: "read-a-run", label: "Read a severity rating" },
      { id: "check-a-claim", label: "Check a claim" },
      { id: "review", label: "Approve, edit or discard" },
      { id: "ask", label: "Ask about past incidents" },
    ],
  },
  { id: "words", label: "Words used in ARIA" },
  { id: "connect", label: "Connect your systems" },
];

export function Guide({ back = null }: { back?: string | null }) {
  return (
    <div className="grid gap-8">
      {back ? (
        // Opened from an incident's "How to read this": the way back, without the browser's Back.
        <Link
          href={back as never}
          className="-mb-4 inline-flex min-h-6 w-fit items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeftIcon aria-hidden className="size-4" />
          Back to the incident
        </Link>
      ) : null}
      <PageHeader
        title="Guide"
        description="ARIA reads an alert and its logs, rates how serious it is, finds what happened before and drafts a report in which every claim names its source. Nothing is sent until a person approves it."
      />
      <OnThisPage items={CONTENTS} variant="chips" />
      <div className="grid gap-12 xl:grid-cols-[minmax(0,1fr)_14rem]">
        <div className="grid min-w-0 gap-16">
          <section aria-labelledby="tasks" className="grid gap-6">
            <SectionHeader
              id="tasks"
              title="Five things to try"
              description="Each takes a minute or two, in this order or any other."
            />
            <ol className="grid gap-4">
              <Task
                id="first-incident"
                number={1}
                title="Triage your first incident"
                action={<StartSample />}
              >
                <p>
                  A sample is real log lines arranged into an incident. ARIA works through it in a
                  few seconds while you watch, then waits for your review. Nothing is sent anywhere.
                </p>
              </Task>
              <Task
                id="read-a-run"
                number={2}
                title="Read a severity rating"
                action={
                  // Arriving here from an incident, the way back sits where the reading starts.
                  back ? (
                    <TaskLink href={back}>Back to the incident</TaskLink>
                  ) : (
                    <TaskLink href="/console/runs">Open your incidents</TaskLink>
                  )
                }
              >
                <p>
                  An incident opens with its level, what that level usually means and the short list
                  of levels it could be. When ARIA isn&apos;t sure, it says so and asks you to
                  confirm.
                </p>
                <p>
                  Under How serious, How ARIA decided shows the rules that matched, the model&apos;s
                  view and how often short lists like this one held the right level.
                </p>
              </Task>
              <Task
                id="check-a-claim"
                number={3}
                title="Check a claim against its evidence"
                action={
                  <TaskLink href="/console/runs?status=published">Open a published report</TaskLink>
                }
              >
                <p>
                  Every statement in a report ends with its sources, such as E3. Point at one to see
                  what it rests on, or click or tap it to keep it open beside the report. The
                  Evidence tab lists everything a report may cite.
                </p>
              </Task>
              <Task
                id="review"
                number={4}
                title="Approve, edit or discard a message"
                action={
                  <TaskLink href="/console/runs?status=awaiting_review">
                    Incidents waiting for you
                  </TaskLink>
                }
              >
                <p>
                  ARIA drafts the report and its messages, and sends nothing until you decide:
                  approve them, edit them first, or discard the draft. Afterwards a note says what
                  happened and when.
                </p>
                <p>
                  On a shared demo the examples stay as they are for everyone. Review an incident
                  you started, or open an example and make your own copy.
                </p>
              </Task>
              <Task
                id="ask"
                number={5}
                title="Ask about past incidents"
                action={<TaskLink href="/console/ask">Ask ARIA</TaskLink>}
              >
                <p>
                  Ask about one incident, or about the past incidents and runbooks ARIA knows. Each
                  answer numbers its sources. ARIA can&apos;t see live systems.
                </p>
              </Task>
            </ol>
          </section>

          <section aria-labelledby="words" className="grid gap-6">
            <SectionHeader
              id="words"
              title="Words used in ARIA"
              description="The same definitions open from any word with a dotted underline."
            />
            <dl className="grid gap-3 sm:grid-cols-2">
              {Object.values(GLOSSARY).map((entry) => (
                <div
                  key={entry.term}
                  className="grid content-start gap-1.5 rounded-card border border-rule bg-raised p-5"
                >
                  <dt className="text-lg font-semibold text-heading">{entry.term}</dt>
                  <dd className="text-base leading-relaxed text-muted-foreground">
                    {entry.definition}
                  </dd>
                </div>
              ))}
            </dl>
          </section>

          <section aria-labelledby="connect" className="grid gap-6">
            <SectionHeader
              id="connect"
              title="Connect ARIA to your systems"
              description="In production most incidents start on their own: from alerts, a scan of a log folder, the command line or other agents."
            />
            <TaskLink href="/console/guide/connect">How to connect each one</TaskLink>
          </section>
        </div>
        <OnThisPage items={CONTENTS} variant="rail" />
      </div>
    </div>
  );
}
