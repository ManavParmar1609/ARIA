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

// The guide, arranged by what a newcomer wants to do (item 26): six short tasks, each with its
// way in beside it, then what keeps ARIA honest, then the words ARIA uses. The samples live on
// New triage and the incident page explains itself where it matters, so neither is repeated here,
// and nothing starts on its own.

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
  const external = /^https?:/.test(href);
  const className =
    "inline-flex items-center gap-1.5 text-sm font-medium underline decoration-control underline-offset-4 hover:text-heading";
  if (external) {
    return (
      <a href={href} className={className}>
        {children}
        <ArrowRightIcon aria-hidden className="size-4" />
      </a>
    );
  }
  return (
    <Link href={href as never} className={className}>
      {children}
      <ArrowRightIcon aria-hidden className="size-4" />
    </Link>
  );
}

/** One safeguard: its name always in view, the detail a click away, one idea per paragraph. */
function Safeguard({
  id,
  title,
  children,
  more,
}: {
  id: string;
  title: string;
  children: ReactNode;
  more?: { href: string; label: string };
}) {
  return (
    <details
      id={id}
      className="group scroll-mt-24 rounded-card border border-rule bg-raised lg:scroll-mt-8"
    >
      <summary className="cursor-pointer rounded-card px-5 py-4 text-lg font-semibold text-heading marker:text-heading/60 hover:bg-sunken/60 sm:px-6">
        {title}
      </summary>
      <div className="grid max-w-prose gap-2 px-5 pt-1 pb-5 text-base leading-relaxed text-foreground sm:px-6 sm:pb-6">
        {children}
        {more ? (
          <div className="pt-1">
            <TaskLink href={more.href}>{more.label}</TaskLink>
          </div>
        ) : null}
      </div>
    </details>
  );
}

// The guide's sections, for its "On this page" list.
const CONTENTS: TocItem[] = [
  {
    id: "tasks",
    label: "Six things to try",
    children: [
      { id: "first-incident", label: "Triage your first incident" },
      { id: "read-a-run", label: "Read a severity rating" },
      { id: "check-a-claim", label: "Check a claim" },
      { id: "review", label: "Approve, edit or discard" },
      { id: "ask", label: "Ask about past incidents" },
      { id: "blind", label: "Check ARIA blind" },
    ],
  },
  { id: "honest", label: "What keeps it honest" },
  { id: "words", label: "Words used in ARIA" },
  { id: "connect", label: "Connect your systems" },
];

export function Guide({
  back = null,
  docs = "",
}: {
  back?: string | null;
  /** Where the written docs live (the model card, the ops runbook), for the way in to each. */
  docs?: string;
}) {
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
        description="ARIA reads an alert and its logs, rates how serious it is and says when a person should decide, finds what happened before and drafts a report in which every claim names its source. Nothing is sent until a person approves it."
      />
      <OnThisPage items={CONTENTS} variant="chips" />
      <div className="grid gap-12 xl:grid-cols-[minmax(0,1fr)_14rem]">
        <div className="grid min-w-0 gap-16">
          <section aria-labelledby="tasks" className="grid gap-6">
            <SectionHeader
              id="tasks"
              title="Six things to try"
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
                  confirm; when it can&apos;t choose between levels, it says which one it plans for.
                </p>
                <p>
                  Under How serious, How ARIA decided shows the rules that matched, the model&apos;s
                  view, how often short lists like this one held the right level, and why a person
                  should confirm: logs unlike anything the model learned from, or a system it never
                  trained on.
                </p>
                <p>
                  The same panel says when errors run far above the system&apos;s usual rate, and
                  when reviewers dismissed the same pattern before.
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
                  approve them, edit them first, or discard the draft. A draft may link only to
                  allowed sites and address only configured recipients; anything else is taken out
                  before you see it, and listed.
                </p>
                <p>
                  Afterwards the incident&apos;s decision record says who decided what, and when. On
                  a shared demo the examples stay as they are for everyone: review an incident you
                  started, or open an example and make your own copy.
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
              <Task
                id="blind"
                number={6}
                title="Check ARIA blind"
                action={
                  <TaskLink href="/console/settings#set-blind">Rate an incident blind</TaskLink>
                }
              >
                <p>
                  In Settings, Check ARIA blind shows a recent incident from its logs alone, without
                  ARIA&apos;s level. Rate it, then see what ARIA said. Ratings given blind are what
                  ARIA recalibrates its short lists on; approvals don&apos;t count, because a person
                  approving a report tends to agree with it.
                </p>
                <p>On a shared demo your rating is not stored, so no visitor can skew the model.</p>
              </Task>
            </ol>
          </section>

          <section aria-labelledby="honest" className="grid gap-6">
            <SectionHeader
              id="honest"
              title="What keeps it honest"
              description="The checks behind a rating and a review. Open one for the detail; Test results and the written docs have the depth."
            />
            <div className="grid gap-3">
              <Safeguard
                id="honest-promise"
                title="A promise for each level"
                more={{ href: "/console/evals#ev-calibration", label: "When it asks a person" }}
              >
                <p>
                  The short list keeps a level only when that level&apos;s own promise says so. SEV1
                  and SEV2 get a tighter promise than SEV3 and SEV4, so a rare serious incident is
                  never left out to make the common ones look good.
                </p>
                <p>
                  The lists also certify a limit on how often a serious incident is rated minor, the
                  mistake that matters most. The tests report that figure first.
                </p>
              </Safeguard>
              <Safeguard
                id="honest-novelty"
                title="Unfamiliar logs go to a person"
                more={{ href: "/console/evals", label: "Test results" }}
              >
                <p>
                  Before deciding, ARIA asks whether the window looks like anything its model
                  learned from. One too far from the training data, with too many patterns new to
                  its system, or from a system the model never saw is never decided alone.
                </p>
                <p>
                  The incident says why a person should confirm, and the short list widens to the
                  levels the rules leave open. The tests hold each system out in turn to measure how
                  ARIA does on one it never saw.
                </p>
              </Safeguard>
              <Safeguard
                id="honest-learning"
                title="Blind checks keep it calibrated"
                more={{ href: "/console/settings#set-drift", label: "Has anything shifted?" }}
              >
                <p>
                  Each blind rating nudges that level&apos;s promise towards its target, and after
                  enough of them replaces the level&apos;s calibration with the checks&apos; own.
                  Nothing else about the model changes, so a recalibration can widen or narrow the
                  lists but never changes which level the model ranks first.
                </p>
                <p>
                  Settings also compares each system&apos;s recent levels with its earlier ones and
                  says when the mix has shifted beyond chance. In the logs an operator watches, an
                  alarm sounds when blind checks show more serious incidents rated minor than the
                  promise allows.
                </p>
              </Safeguard>
              <Safeguard
                id="honest-record"
                title="Every decision is on the record"
                more={{ href: "/console/settings#set-record", label: "Verify the record" }}
              >
                <p>
                  Every review, edit, publish, message sent, blind check, recalibration, purge and
                  deletion is one entry on an append-only record, each chained by a hash to the one
                  before it. Change, remove or reorder an entry and every later link breaks, which
                  Settings and the command line report.
                </p>
                <p>
                  Incidents are kept until you delete them, or until a retention period an operator
                  sets. The record keeps their entries either way.
                </p>
              </Safeguard>
              <Safeguard
                id="honest-model"
                title="A language model can choose, not invent"
                more={
                  docs ? { href: `${docs}/threat-model.md`, label: "The threat model" } : undefined
                }
              >
                <p>
                  A model may pick a level only from the short list, and its report must cite
                  evidence for every claim, or the plain draft stands. A critic reads the draft,
                  removes claims the evidence doesn&apos;t support and says when it can&apos;t
                  judge.
                </p>
                <p>
                  A model that declines or is cut off fails that call and the next model takes it,
                  each call sent once. Before anything is sent, the approval is saved, so a process
                  that stops mid-way sends each approved message once when it resumes.
                </p>
              </Safeguard>
            </div>
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
