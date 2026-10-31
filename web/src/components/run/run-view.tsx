"use client";

import {
  CircleHelpIcon,
  DownloadIcon,
  HistoryIcon,
  MessageSquareTextIcon,
  Trash2Icon,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { LevelChip } from "@/components/aria/severity";
import { runTitle } from "@/components/console/run-row";
import { useDocumentTitle } from "@/lib/document-title";
import { EmptyState, ErrorState, LoadingRows } from "@/components/console/states";
import { LostSpot } from "@/components/illustrations/spots";
import { ExampleStatus, RunStatus } from "@/components/console/status";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError } from "@/lib/api/client";
import { useDeleteRun, useRun, useRunState, useSession, useSettingsView } from "@/lib/api/hooks";
import { useRunTimeline } from "@/lib/api/stream";
import {
  isSeverity,
  type ReviewPrompt,
  type RunDetail,
  type RunStateValues,
  type SeverityAssessment,
} from "@/lib/api/types";
import { absoluteTime, relativeTime, stripSeverity, writtenOffline } from "@/lib/format";
import { shortListText } from "@/lib/levels";
import { waitingText } from "@/lib/queue";
import { systemName, triggerLabel } from "@/lib/systems";

import { Activity } from "./activity";
import { Deliveries } from "./deliveries";
import { EvidencePanel, EvidenceProvider } from "./evidence";
import { ExpertCheck } from "./expert-check";
import { History, checkpointName } from "./history";
import { RunProgress, usePacedSteps } from "./progress";
import { LiveDraft, ReportView } from "./report-view";
import { ExampleNote } from "./example-note";
import { Receipt, type ReceiptFacts } from "./receipt";
import { ReviewPanel } from "./review-panel";
import { HarmlessNote, SampleNext, sampleOf } from "./sample-next";
import { EvidenceTable, Templates } from "./run-tabs";
import { SeenBefore } from "./seen-before";
import { SeverityPanel } from "./severity-panel";
import { AgentTeam } from "./team";
import { WhatHappened } from "./what-happened";

const ACTIVE = new Set(["queued", "running", "awaiting_review"]);
const WORKING = new Set(["queued", "running"]);

/** The parts of a run's state that the steps a playback has shown would have produced. */
function reached(values: RunStateValues, passed: ReadonlySet<string>): RunStateValues {
  const wrote = passed.has("write");
  return {
    ...values,
    batch: passed.has("read") ? values.batch : undefined,
    severity: passed.has("rate") ? values.severity : undefined,
    retrieval: passed.has("recall") ? values.retrieval : undefined,
    investigation: passed.has("investigate") ? values.investigation : undefined,
    report: wrote ? values.report : undefined,
    actions: wrote ? values.actions : undefined,
    evidence: wrote ? values.evidence : undefined,
  };
}

const TABS_KEY = "aria:run-tabs";
const TABS = new Set(["work", "evidence", "logs", "history"]);
const KEPT_TABS = 20;

/** The tab each recent incident was left on in this browser tab, so Back returns to it. */
function storedTabs(): Record<string, string> {
  try {
    const raw = JSON.parse(window.sessionStorage.getItem(TABS_KEY) ?? "{}") as unknown;
    return raw && typeof raw === "object" && !Array.isArray(raw)
      ? (raw as Record<string, string>)
      : {};
  } catch {
    return {};
  }
}

function storedTab(runId: string): string {
  if (typeof window === "undefined") return "work";
  const tab = storedTabs()[runId];
  return typeof tab === "string" && TABS.has(tab) ? tab : "work";
}

function storeTab(runId: string, tab: string) {
  // The newest last, and only the most recent few.
  const kept = Object.entries(storedTabs()).filter(([id]) => id !== runId);
  kept.push([runId, tab]);
  try {
    window.sessionStorage.setItem(
      TABS_KEY,
      JSON.stringify(Object.fromEntries(kept.slice(-KEPT_TABS))),
    );
  } catch {
    // Private windows can refuse storage; the tab then simply opens on its first tab.
  }
}

/** The answer first (item 14): the level and its word, the title, and the short list of levels
 * it could be; then where the incident came from. */
function Header({
  run,
  assessment,
  shared = false,
}: {
  run: RunDetail;
  assessment: SeverityAssessment | undefined;
  /** A shared demo, where each visitor's incidents are theirs alone. */
  shared?: boolean;
}) {
  const level = assessment?.severity ?? run.severity;
  // Arriving here, from New triage or a link, puts focus on the incident's title (item 35).
  const title = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    title.current?.focus({ preventScroll: true });
  }, []);
  return (
    <header className="grid gap-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <LevelChip severity={isSeverity(level) ? level : null} />
        {run.example ? <ExampleStatus status={run.status} /> : <RunStatus status={run.status} />}
      </div>
      <h1
        ref={title}
        tabIndex={-1}
        className="text-2xl leading-tight tracking-heading wrap-anywhere outline-none sm:text-3xl"
      >
        {runTitle(run)}
      </h1>
      <StatusAnnouncer status={run.status} />
      {assessment ? <p className="text-base">{shortListText(assessment, run.status)}</p> : null}
      <p className="text-sm text-muted-foreground">
        {/* A fork says so once, with a link to the run it came from (below). */}
        {systemName(run.system)},{" "}
        {run.parent_run_id
          ? ""
          : `${run.example ? "an example every visitor sees" : triggerLabel(run.trigger)}, `}
        <time dateTime={run.created_at} title={absoluteTime(run.created_at)}>
          {relativeTime(run.created_at)}
        </time>
        {run.parent_run_id ? (
          <>
            , copied from{" "}
            <Link
              href={`/console/runs/${encodeURIComponent(run.parent_run_id)}` as never}
              className="underline decoration-control underline-offset-2"
            >
              the original incident
            </Link>
          </>
        ) : null}
        {/* A link sent to someone else opens nothing for them: say so before they try. */}
        {shared && !run.example ? ". Only your browser can open this incident's link." : null}
      </p>
    </header>
  );
}

// What a screen reader hears as a triage moves on while its page is open (item 35).
const ANNOUNCE: Record<string, string> = {
  queued: "Triage started. It is waiting for a free place.",
  running: "ARIA is working on this incident.",
  awaiting_review: "ARIA has finished, and the incident waits for your review.",
  published: "Published.",
  rejected: "Discarded.",
  failed: "The triage failed.",
};

/** Announces the run's progress, but only for a run that was still going when the page opened:
 * opening a finished incident announces nothing. */
function StatusAnnouncer({ status }: { status: string }) {
  const [watching] = useState(() => ACTIVE.has(status));
  return (
    <p className="sr-only" aria-live="polite">
      {watching ? (ANNOUNCE[status] ?? "") : ""}
    </p>
  );
}

/** Model and tool use in words, for the progress line. ``offline`` is null while unknown. */
function workFacts(run: RunDetail, offline: boolean | null): string {
  const budget = (run.budget ?? {}) as Record<string, unknown>;
  const llmCalls = Number(budget.llm_calls ?? 0);
  const tools = Number(budget.tool_calls ?? 0);
  const model =
    offline === null
      ? ""
      : llmCalls && !offline
        ? `${llmCalls} model calls, ${((run.tokens_in ?? 0) + (run.tokens_out ?? 0)).toLocaleString("en")} tokens`
        : "offline: no language model";
  const toolText = tools ? `${tools} tool ${tools === 1 ? "call" : "calls"}` : "";
  return [model, toolText].filter(Boolean).join(", ");
}

function DeleteRun({ runId, shared = false }: { runId: string; shared?: boolean }) {
  const router = useRouter();
  const remove = useDeleteRun();
  const deleting = useRef(false);
  const [open, setOpen] = useState(false);
  const error = remove.error instanceof ApiError ? remove.error.detail : remove.error?.message;
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="ghost">
          <Trash2Icon aria-hidden />
          Delete
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete this incident?</DialogTitle>
          <DialogDescription>
            {shared
              ? "The incident, its report and its steps are removed. This cannot be undone."
              : "The incident, its report, its steps and what it added to the incident library are removed. This cannot be undone."}
          </DialogDescription>
        </DialogHeader>
        {error ? (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        ) : null}
        <DialogFooter>
          <Button onClick={() => setOpen(false)}>Keep it</Button>
          <Button
            variant="danger"
            disabled={remove.isPending}
            onClick={() => {
              // A double click would send a second delete, which fails once the first succeeds.
              if (deleting.current) return;
              deleting.current = true;
              remove.mutate(runId, {
                onSuccess: () => {
                  toast.success("Incident deleted");
                  router.push("/console/runs");
                },
                onError: () => {
                  deleting.current = false;
                },
              });
            }}
          >
            {remove.isPending ? "Deleting" : "Delete the incident"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Where the incident sits: the incidents list, then its title, or "New incident" until ARIA has
 * named it. */
function Crumbs({ title }: { title?: string | null }) {
  return (
    // One line: a long title ends in an ellipsis here, and the heading below gives it in full.
    <nav
      aria-label="Breadcrumb"
      className="flex min-w-0 items-center text-sm text-muted-foreground"
    >
      <Link
        href="/console/runs"
        className="inline-flex min-h-6 shrink-0 items-center hover:text-foreground"
      >
        Incidents
      </Link>
      <span aria-hidden className="shrink-0 px-2 text-faint">
        /
      </span>
      <span aria-current="page" className="min-w-0 truncate">
        {title || "New incident"}
      </span>
    </nav>
  );
}

/** The run page's shape while it loads: header, progress, then the panels. */
function RunSkeleton() {
  return (
    <div role="status" className="grid gap-8">
      <span className="sr-only">Loading the incident</span>
      <div className="grid gap-3">
        <Skeleton className="h-7 w-40" />
        <Skeleton className="h-9 w-[32rem] max-w-full" />
        <Skeleton className="h-5 w-72 max-w-full" />
      </div>
      <Skeleton className="h-24 w-full" />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_24rem] xl:gap-8">
        <Skeleton className="h-[32rem] w-full" />
        <div className="grid content-start gap-6">
          <Skeleton className="h-64 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      </div>
    </div>
  );
}

// Runs that ended with no rating, so the severity panel says so instead of waiting for one.
const ENDED_UNRATED = new Set(["failed", "rejected", "published"]);

/** The step an earlier view stops before, in the history list's words: "before “Rate severity”". */
function earlierStep(next: string[]): string {
  const name = checkpointName({ next, interrupted: false });
  return name.charAt(0).toLowerCase() + name.slice(1);
}

export function RunView({
  runId,
  shortListHeld,
}: {
  runId: string;
  /** How often the short list held the right level on the published test incidents. */
  shortListHeld?: number | null;
}) {
  const run = useRun(runId);
  const settings = useSettingsView().data;
  const shared = settings?.visitor_scope ?? false;
  const session = useSession().data;
  // Set when this page saved the review, so the receipt that replaces the panel takes focus.
  const [decided, setDecided] = useState(false);
  // A link that names no incident (deleted, someone else's, or damaged in copying) opens the
  // same "not here" page, with a title that says so.
  const missing = run.error instanceof ApiError && [400, 404, 422].includes(run.error.status);
  useDocumentTitle(run.data ? runTitle(run.data) : missing ? "Incident not found" : null);
  const [checkpoint, setCheckpoint] = useState<string | null>(null);
  const [tab, setTab] = useState(() => storedTab(runId));
  const chooseTab = (next: string) => {
    setTab(next);
    storeTab(runId, next);
  };
  const status = run.data?.status;
  // Followed live only while ARIA works: a paused or finished run is read once, and again when
  // its status moves on (stream.ts says why).
  const mode = !run.data ? "off" : WORKING.has(run.data.status) ? "live" : "stored";
  const timeline = useRunTimeline(runId, mode, status);
  const progress = usePacedSteps(runId, timeline.events, status);
  // Fetched alongside the run, not after it; a queued run has no state yet.
  const state = useRunState(runId, checkpoint, status !== "queued");
  // While a run that finished in a blink plays its steps back, each part of the page arrives as
  // the trace reaches its step, so nothing shows before its step or goes away again (M1, J-M6).
  const full = state.data?.values;
  const values = progress.playing && full ? reached(full, progress.passed) : full;
  const evidence = useMemo(() => values?.evidence ?? values?.report?.evidence ?? [], [values]);
  const events = useMemo(() => values?.batch?.events ?? [], [values]);
  const cited = useMemo(() => new Set((values?.report?.evidence ?? []).map((e) => e.id)), [values]);
  const messageTitles = useMemo(
    () => Object.fromEntries((values?.actions ?? []).map((a) => [a.action_id, a.title])),
    [values],
  );

  // One placeholder in the page's final shape until the run and its state are both in, so the
  // page does not jump as each part arrives. A running run shows at once: it changes as it goes.
  const stateLoading = state.isPending && state.fetchStatus === "fetching" && status !== "running";
  if (run.isPending || (run.isSuccess && stateLoading)) return <RunSkeleton />;
  // A refresh that fails (a busy server, say) keeps what the page already shows; one that finds
  // the incident gone (deleted in another tab) says so instead (FL-08).
  if (run.isError && (!run.data || missing)) {
    if (missing) {
      return (
        <EmptyState
          heading="h1"
          title="This incident is not here"
          art={<LostSpot className="h-auto w-full" />}
          action={
            <Button asChild size="sm">
              <Link href="/console/runs">Back to incidents</Link>
            </Button>
          }
        >
          {shared
            ? "The link may be wrong, or the incident was deleted. On this shared demo, each visitor sees only the incidents they started, so a link from someone else's browser opens nothing here."
            : "It may have been deleted, or the link is wrong."}
        </EmptyState>
      );
    }
    return (
      <div className="grid gap-6">
        <Crumbs />
        <ErrorState
          title="This incident could not be loaded"
          error={run.error}
          onRetry={() => void run.refetch()}
          action={
            <Button asChild size="sm" variant="ghost">
              <Link href="/console/runs">Back to incidents</Link>
            </Button>
          }
        />
      </div>
    );
  }

  const detail: RunDetail = progress.playing
    ? { ...run.data, status: "running", severity: null, report_id: null, latency_ms: null }
    : run.data;
  const prompt =
    detail.status === "awaiting_review" ? (detail.review as ReviewPrompt | null) : null;
  const report = values?.report;
  // Until the report is in, whether a model wrote it is not known (null), so nothing is claimed.
  const offline = report ? writtenOffline(report) : null;
  const severity = values?.severity;
  const liveText = timeline.liveText.report ?? "";
  const viewing = checkpoint ? state.data : null;
  const terminal = !ACTIVE.has(detail.status);
  const sample = detail.trigger === "sample" ? sampleOf(values?.request) : null;
  const review = values?.review;
  const receipt: ReceiptFacts | null =
    review && !viewing && !detail.example && ["published", "rejected"].includes(detail.status)
      ? {
          status: detail.status,
          decision: review.decision,
          reviewer: review.reviewer,
          you: session?.signedIn
            ? session.name === review.reviewer
            : review.reviewer === "anonymous",
          at: detail.updated_at,
          actions: values?.actions ?? [],
          deliveries: detail.deliveries ?? [],
          connected: (kind) => settings?.channels?.[kind] ?? false,
          shared,
        }
      : null;

  return (
    <EvidenceProvider evidence={evidence} events={events} besidePanel="(min-width: 1280px)">
      <div className="grid grid-cols-[minmax(0,1fr)] gap-6">
        <div className="flex min-h-8 flex-wrap items-center justify-between gap-x-3 gap-y-1">
          <Crumbs title={detail.title ? runTitle(detail) : null} />
          <div className="flex flex-wrap gap-1.5">
            <Button asChild size="sm" variant="ghost">
              <Link
                href={
                  `/console/guide?from=${encodeURIComponent(`/console/runs/${detail.id}`)}#read-a-run` as never
                }
              >
                <CircleHelpIcon aria-hidden />
                How to read this
              </Link>
            </Button>
            {/* A sample's page offers this under What next?; every other incident has it here. */}
            {detail.trigger === "sample" ? null : (
              <Button asChild size="sm" variant="ghost">
                <Link href={`/console/ask?run=${encodeURIComponent(detail.id)}` as never}>
                  <MessageSquareTextIcon aria-hidden />
                  Ask about it
                </Link>
              </Button>
            )}
            {detail.report_id && !receipt ? (
              <>
                <Button asChild size="sm" variant="ghost">
                  <a
                    href={`/api/v1/runs/${encodeURIComponent(detail.id)}/report.md`}
                    download={`${detail.id}-report.md`}
                  >
                    <DownloadIcon aria-hidden />
                    Report (Markdown)
                  </a>
                </Button>
                {detail.status === "published" ? (
                  <Button asChild size="sm" variant="ghost">
                    <a
                      href={`/api/v1/runs/${encodeURIComponent(detail.id)}/postmortem.md`}
                      download={`${detail.id}-postmortem.md`}
                    >
                      <DownloadIcon aria-hidden />
                      Postmortem draft (Markdown)
                    </a>
                  </Button>
                ) : null}
              </>
            ) : null}
            {/* Waiting for review counts as done enough: nothing more runs until a person acts. */}
            {(terminal || detail.status === "awaiting_review") && !detail.example ? (
              <DeleteRun runId={detail.id} shared={shared} />
            ) : null}
          </div>
        </div>

        <Header run={detail} assessment={severity} shared={shared} />

        {viewing ? (
          <div
            role="status"
            className="sticky top-[4.75rem] z-20 flex flex-wrap items-center justify-between gap-3 rounded-lg bg-raised px-4 py-3 text-sm ring-1 ring-primary lg:top-3"
          >
            <span className="flex items-center gap-2">
              <HistoryIcon aria-hidden className="size-4" />
              You are looking at this incident as it was earlier: {earlierStep(viewing.next)}.
            </span>
            <Button size="sm" onClick={() => setCheckpoint(null)}>
              Back to now
            </Button>
          </div>
        ) : null}

        {detail.status === "failed" ? (
          <ErrorState
            title="This run failed"
            error={new Error(detail.error ?? "No error message was recorded.")}
          />
        ) : null}

        {sample && !viewing ? (
          <HarmlessNote sample={sample} severity={severity?.severity ?? detail.severity} />
        ) : null}

        {detail.example && !viewing && (prompt || (terminal && detail.status !== "failed")) ? (
          <ExampleNote runId={detail.id} />
        ) : prompt && !viewing ? (
          <ReviewPanel
            runId={detail.id}
            prompt={prompt}
            actions={values?.actions ?? []}
            report={report}
            onDecided={() => setDecided(true)}
          />
        ) : receipt ? (
          <Receipt
            runId={detail.id}
            facts={receipt}
            comment={review?.comment}
            focusOnMount={decided}
          />
        ) : null}
        {detail.deliveries?.length && !viewing ? (
          <Deliveries
            runId={detail.id}
            deliveries={detail.deliveries}
            ended={terminal}
            readOnly={detail.example}
          />
        ) : null}

        <RunProgress
          steps={progress.steps}
          status={detail.status}
          latencyMs={detail.latency_ms}
          facts={workFacts(detail, offline)}
        />

        {state.isError && !state.data ? (
          <ErrorState
            title="The incident's details could not be loaded"
            error={state.error}
            onRetry={() => void state.refetch()}
          />
        ) : null}

        {/* Four panels, one question each (item 13). On a wide screen the severity and the past
            incidents sit beside the other two, and stay in view while the report scrolls. */}
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_24rem] xl:grid-rows-[auto_auto_1fr] xl:gap-x-8">
          <div className="min-w-0 xl:col-start-1 xl:row-start-1">
            {values?.batch ? (
              <WhatHappened batch={values.batch} timeline={report?.timeline ?? []} />
            ) : detail.status === "queued" ? (
              <EmptyState title="Waiting to start">{waitingText(detail.ahead)}</EmptyState>
            ) : (
              <LoadingRows rows={4} label="Reading the logs" />
            )}
          </div>
          <div className="grid min-w-0 [scrollbar-width:thin] content-start gap-6 xl:sticky xl:top-6 xl:col-start-2 xl:row-span-3 xl:row-start-1 xl:max-h-[calc(100dvh-3rem)] xl:self-start xl:overflow-y-auto">
            {severity ? (
              <SeverityPanel
                assessment={severity}
                shortListHeld={shortListHeld}
                status={detail.status}
              />
            ) : (
              <section
                aria-labelledby="severity-title"
                className="grid gap-2 rounded-lg bg-raised p-5"
              >
                <h2 id="severity-title" className="text-base font-medium">
                  How serious
                </h2>
                <p className="max-w-prose text-sm text-muted-foreground">
                  {ENDED_UNRATED.has(detail.status)
                    ? "This triage ended before ARIA rated it."
                    : "ARIA rates the incident once it has read the logs."}
                </p>
              </section>
            )}
            <EvidencePanel />
          </div>
          <div className="min-w-0 xl:col-start-1 xl:row-start-2">
            <SeenBefore
              incidents={report?.similar_incidents ?? values?.retrieval?.incidents ?? []}
              retrieval={values?.retrieval}
              system={detail.system}
            />
          </div>
          <div className="min-w-0 xl:col-start-1 xl:row-start-3">
            {report ? (
              <ReportView
                report={report}
                titleHidden={stripSeverity(report.title) === runTitle(detail)}
              />
            ) : liveText ? (
              <LiveDraft text={liveText} />
            ) : state.isPending && status !== "queued" ? (
              <LoadingRows rows={4} label="Loading the report" />
            ) : (
              <EmptyState title="No report yet">
                ARIA writes the report after it has rated the severity, looked for similar incidents
                and investigated.
              </EmptyState>
            )}
          </div>
        </div>

        {detail.trigger === "replay" ? <ExpertCheck runId={detail.id} /> : null}
        {sample &&
        (terminal || detail.status === "awaiting_review") &&
        detail.status !== "failed" &&
        !viewing ? (
          // Once ARIA's part is over: the next steps, and beside a bigger run, both ratings. It
          // reads ?compare= from the address.
          <Suspense fallback={null}>
            <SampleNext
              runId={detail.id}
              sample={sample}
              severity={severity?.severity ?? detail.severity}
              waiting={detail.status === "awaiting_review"}
            />
          </Suspense>
        ) : null}

        <Tabs value={tab} onValueChange={chooseTab} className="mt-2">
          <TabsList aria-label="Run details">
            <TabsTrigger value="work">What ARIA did</TabsTrigger>
            <TabsTrigger value="evidence">Evidence ({evidence.length})</TabsTrigger>
            <TabsTrigger value="logs">Logs</TabsTrigger>
            <TabsTrigger value="history">History</TabsTrigger>
          </TabsList>
          <TabsContent value="work" className="grid gap-6">
            {values ? (
              <AgentTeam values={values} events={timeline.events} example={detail.example} />
            ) : (
              <LoadingRows rows={3} label="Loading what the agents did" />
            )}
            <details className="text-sm">
              <summary className="w-fit cursor-pointer py-0.5 font-medium">
                Every event ({timeline.events.length})
              </summary>
              <div className="grid gap-2 pt-3">
                {mode === "live" ? (
                  <p className="text-xs text-muted-foreground" role="status">
                    {timeline.state === "live"
                      ? "Live: following the triage as it happens."
                      : timeline.state === "reconnecting"
                        ? "Reconnecting to the live updates."
                        : timeline.state === "closed"
                          ? "Live updates ended."
                          : "Connecting to the live updates."}
                  </p>
                ) : null}
                <Activity
                  events={timeline.events}
                  offline={offline ?? undefined}
                  titles={messageTitles}
                />
              </div>
            </details>
          </TabsContent>
          <TabsContent value="evidence">
            {evidence.length ? (
              <EvidenceTable evidence={evidence} cited={cited} />
            ) : (
              <p className="text-sm text-muted-foreground">No evidence yet.</p>
            )}
          </TabsContent>
          <TabsContent value="logs">
            {values?.batch ? (
              <Templates batch={values.batch} />
            ) : (
              <p className="text-sm text-muted-foreground">The logs have not been parsed yet.</p>
            )}
          </TabsContent>
          <TabsContent value="history">
            <History runId={detail.id} viewing={checkpoint} onView={setCheckpoint} />
          </TabsContent>
        </Tabs>
      </div>
    </EvidenceProvider>
  );
}
