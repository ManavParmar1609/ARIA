"use client";

import {
  ChevronDownIcon,
  CircleHelpIcon,
  DownloadIcon,
  HistoryIcon,
  MessageSquareTextIcon,
  Trash2Icon,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
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
import { orList, shortListText, unsettled } from "@/lib/levels";
import { waitingText } from "@/lib/queue";
import { systemName, triggerLabel } from "@/lib/systems";
import { cn } from "@/lib/utils";

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
    // With the logs, so the patterns What happened cites resolve at once instead of reading as
    // missing sources until the report is written (NV-M2). Nothing else shows it before its step.
    evidence: passed.has("read") ? values.evidence : undefined,
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

/** One line on what a part of the technical details shows, for someone opening it first. */
function TabNote({ children }: { children: ReactNode }) {
  return <p className="max-w-prose text-base text-muted-foreground">{children}</p>;
}

function hasStoredTab(runId: string): boolean {
  return typeof window !== "undefined" && runId in storedTabs();
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

/** What the header says of the rating: its badge, when the level is unsettled, and the sentence
 * under the title. A level still open is said as a plan, not as a finding (S2). */
export function headerRating(
  assessment: SeverityAssessment,
  status: string,
): { badge: string | null; sentence: string } {
  if (!unsettled(assessment, status)) {
    return { badge: null, sentence: shortListText(assessment, status) };
  }
  if (status === "rejected") {
    // A discarded draft waits for no one: its short list says what ARIA had planned.
    return { badge: "Not rated", sentence: shortListText(assessment, status) };
  }
  return {
    badge: "Not rated: needs a person",
    sentence: `Could be ${orList(assessment.prediction_set)}. ARIA plans for ${assessment.severity} until someone decides.`,
  };
}

// A title longer than this takes a smaller size, so it does not fill a phone's first screen (L10).
const LONG_TITLE = 80;

/** The answer first (item 14): the level and its word, the title, and the short list of levels
 * it could be; then where the incident came from. */
function Header({
  run,
  assessment,
  shortList = true,
  replaying = false,
  now = false,
  shared = false,
}: {
  run: RunDetail;
  /** The rating, once the steps on show have reached it, as the panels below show it. */
  assessment: SeverityAssessment | undefined;
  /** The short list's sentence. A playback holds it back until the strip folds, so the header
   * does not grow under the strip while the visitor watches it (SL-M1). */
  shortList?: boolean;
  /** A finished run's steps play back: nothing claims ARIA is still at work (S5). */
  replaying?: boolean;
  /** History shows an earlier step below, and the header the incident as it is now (S7). */
  now?: boolean;
  /** A shared demo, where each visitor's incidents are theirs alone. */
  shared?: boolean;
}) {
  const level = assessment?.severity ?? run.severity;
  const rating = assessment ? headerRating(assessment, run.status) : null;
  const title = runTitle(run);
  // Arriving here, from New triage or a link, puts focus on the incident's title (item 35).
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
  }, []);
  return (
    <header className="grid gap-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {now ? (
          <span className="text-sm font-medium text-muted-foreground">As it is now:</span>
        ) : null}
        {rating?.badge ? (
          // Drawn like "Not rated yet": dashed and in ink, with no level's colour.
          <span className="inline-flex h-7 items-center rounded-sm border border-dashed border-control px-2.5 text-sm font-medium text-faint">
            {rating.badge}
          </span>
        ) : (
          <LevelChip severity={isSeverity(level) ? level : null} />
        )}
        {run.example ? <ExampleStatus status={run.status} /> : <RunStatus status={run.status} />}
      </div>
      <h1
        ref={heading}
        tabIndex={-1}
        className={cn(
          "leading-tight tracking-heading wrap-anywhere outline-none",
          title.length > LONG_TITLE ? "text-xl sm:text-2xl" : "text-2xl sm:text-3xl",
        )}
      >
        {title}
      </h1>
      <StatusAnnouncer status={run.status} replaying={replaying} />
      {rating && shortList ? <p className="text-base">{rating.sentence}</p> : null}
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
 * opening a finished incident announces nothing. While a finished run's steps play back it says
 * nothing either, and then how the run ended, once the playback has caught up (S5). */
function StatusAnnouncer({ status, replaying }: { status: string; replaying: boolean }) {
  const [watching] = useState(() => ACTIVE.has(status));
  return (
    <p className="sr-only" aria-live="polite">
      {watching && !replaying ? (ANNOUNCE[status] ?? "") : ""}
    </p>
  );
}

/**
 * Marks the ends of a box that scrolls on its own, `data-more-start` and `data-more-end`, while
 * they hold more than it shows, so a fade there can say so (M6, L6). A callback ref, so it starts
 * whenever the box appears; it watches the box and the one element in it, whose size changes as
 * a section inside opens.
 */
function useScrollEnds(axis: "x" | "y") {
  return useCallback(
    (box: HTMLElement | null) => {
      if (!box || typeof ResizeObserver === "undefined") return;
      const mark = () => {
        const [at, shown, whole] =
          axis === "x"
            ? [box.scrollLeft, box.clientWidth, box.scrollWidth]
            : [box.scrollTop, box.clientHeight, box.scrollHeight];
        box.toggleAttribute("data-more-start", at > 1);
        box.toggleAttribute("data-more-end", at + shown < whole - 1);
      };
      const resize = new ResizeObserver(mark);
      resize.observe(box);
      if (box.firstElementChild) resize.observe(box.firstElementChild);
      box.addEventListener("scroll", mark, { passive: true });
      return () => {
        resize.disconnect();
        box.removeEventListener("scroll", mark);
      };
    },
    [axis],
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
  // The title as the page first saw it: a playback keeps it until the trace folds, so the header
  // does not grow under the strip while the visitor watches it (SL-M1).
  const [openedTitle, setOpenedTitle] = useState<string | null | undefined>(undefined);
  if (openedTitle === undefined && run.data) setOpenedTitle(run.data.title ?? null);
  const [checkpoint, setCheckpoint] = useState<string | null>(null);
  const [tab, setTab] = useState(() => storedTab(runId));
  const chooseTab = (next: string) => {
    setTab(next);
    storeTab(runId, next);
  };
  // Folded until asked for, and kept open on an incident whose details were opened before.
  const [technical, setTechnical] = useState(() => hasStoredTab(runId));
  const status = run.data?.status;
  // Followed live only while ARIA works: a paused or finished run is read once, and again when
  // its status moves on (stream.ts says why).
  const mode = !run.data ? "off" : WORKING.has(run.data.status) ? "live" : "stored";
  const timeline = useRunTimeline(runId, mode, status);
  const progress = usePacedSteps(runId, timeline.events, status);
  // Fetched alongside the run, not after it; a queued run has no state yet.
  const state = useRunState(runId, checkpoint, status !== "queued");
  // The incident as it is now, as read before History opened an earlier step: the header goes on
  // showing it, marked so, while the panels below show that step (S7).
  const head = useRunState(runId, null, false).data?.values;
  // While a run that finished in a blink plays its steps back, each part of the page arrives as
  // the trace reaches its step, so nothing shows before its step or goes away again (M1, J-M6).
  const full = state.data?.values;
  const values = progress.playing && full ? reached(full, progress.passed) : full;
  // Edges that fade while the side column or the row of tabs holds more than it shows.
  const sideEnds = useScrollEnds("y");
  const tabEnds = useScrollEnds("x");
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

  const severity = values?.severity;
  const detail: RunDetail = progress.playing
    ? {
        ...run.data,
        status: "running",
        // Rated once the "Rate severity" step has played, as the panels below show it (P8, S5).
        severity: severity?.severity ?? null,
        report_id: null,
        latency_ms: null,
        title: openedTitle ?? null,
      }
    : run.data;
  // A finished run whose steps play back, said so rather than passed off as live.
  const replaying = progress.playing && !WORKING.has(run.data.status);
  // A copy carries its rating over from the original: it shows whole from the first frame.
  const ratingCarried = progress.steps.some((step) => step.key === "rate" && step.copied);
  const prompt =
    detail.status === "awaiting_review" ? (detail.review as ReviewPrompt | null) : null;
  const report = values?.report;
  // Until the report is in, whether a model wrote it is not known (null), so nothing is claimed.
  const offline = report ? writtenOffline(report) : null;
  // The report writer's words as they stream; a playback shows the finished report at its step.
  const liveText = progress.playing ? "" : (timeline.liveText.report ?? "");
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

        <Header
          run={detail}
          assessment={viewing ? head?.severity : severity}
          shortList={!progress.playing || ratingCarried}
          replaying={replaying}
          now={Boolean(viewing)}
          shared={shared}
        />

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

        {/* Above the review: when ARIA's part ends, the strip folds where it is, and the review
            arrives below it instead of pushing the strip down (SL-M1). */}
        <RunProgress
          steps={progress.steps}
          status={detail.status}
          latencyMs={detail.latency_ms}
          facts={workFacts(detail, offline)}
          replaying={replaying}
          onSkip={progress.skip}
        />

        {sample && !viewing ? (
          <HarmlessNote sample={sample} severity={severity?.severity ?? detail.severity} />
        ) : null}

        {detail.example && !viewing && (prompt || (terminal && detail.status !== "failed")) ? (
          <ExampleNote runId={detail.id} />
        ) : prompt && !viewing ? (
          <ReviewPanel
            className="duration-(--duration-moderate) ease-(--ease-out) motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-bottom-2"
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

        {state.isError && !state.data ? (
          <ErrorState
            title="The incident's details could not be loaded"
            error={state.error}
            onRetry={() => void state.refetch()}
          />
        ) : null}

        {/* Four panels, one question each (item 13), the report first: it says in words what
            happened and what to do. On a wide screen the severity and the evidence sit beside it,
            and stay in view while the report scrolls; the logs and past incidents follow it. */}
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_24rem] xl:grid-rows-[auto_auto_1fr] xl:gap-x-8">
          {/* Beside the report it scrolls on its own once a section in it opens: its edges fade
              while they hold more, and focus stops clear of the fades (M6). */}
          <div
            ref={sideEnds}
            className="min-w-0 [scrollbar-width:thin] xl:sticky xl:top-6 xl:col-start-2 xl:row-span-3 xl:row-start-1 xl:max-h-[calc(100dvh-3rem)] xl:scroll-pt-6 xl:scroll-pb-12 xl:self-start xl:overflow-y-auto xl:data-more-end:mask-b-from-[calc(100%-3rem)] xl:data-more-start:mask-t-from-[calc(100%-1.5rem)]"
          >
            <div className="grid content-start gap-6">
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
                  <h2 id="severity-title" className="text-xl">
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
          </div>
          <div className="min-w-0 xl:col-start-1 xl:row-start-1">
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
          <div className="min-w-0 xl:col-start-1 xl:row-start-2">
            {values?.batch ? (
              <WhatHappened batch={values.batch} timeline={report?.timeline ?? []} />
            ) : detail.status === "queued" ? (
              <EmptyState title="Waiting to start">{waitingText(detail.ahead)}</EmptyState>
            ) : (
              <LoadingRows rows={4} label="Reading the logs" />
            )}
          </div>
          <div className="min-w-0 xl:col-start-1 xl:row-start-3">
            <SeenBefore
              incidents={report?.similar_incidents ?? values?.retrieval?.incidents ?? []}
              retrieval={values?.retrieval}
              system={detail.system}
            />
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

        <details
          open={technical}
          onToggle={(event) => setTechnical(event.currentTarget.open)}
          className="group/technical mt-2 rounded-card border border-rule bg-raised"
        >
          <summary className="flex cursor-pointer items-start justify-between gap-4 p-5 sm:p-6 [&::-webkit-details-marker]:hidden">
            <span className="grid gap-1">
              <span className="text-xl font-semibold text-heading">Technical details</span>
              <span className="max-w-prose text-base text-muted-foreground">
                For engineers: what each part of ARIA did, all the evidence, the logs as ARIA read
                them, and the incident&apos;s history.
              </span>
            </span>
            <ChevronDownIcon
              aria-hidden
              className="mt-1 size-5 shrink-0 text-muted-foreground transition-transform duration-(--duration-quick) group-open/technical:rotate-180 motion-reduce:transition-none"
            />
          </summary>
          <div className="border-t border-rule p-5 sm:p-6">
            <Tabs value={tab} onValueChange={chooseTab}>
              {/* One row at any width: on a phone the row scrolls sideways, its edges fade while
                  there is more, and the selected tab's line stays under it (L6). The arrow keys
                  bring each tab into view, clear of the fades. */}
              <div
                ref={tabEnds}
                className="scroll-px-10 [scrollbar-width:thin] overflow-x-auto [contain:inline-size] data-more-end:mask-r-from-[calc(100%-2.5rem)] data-more-start:mask-l-from-[calc(100%-2.5rem)]"
              >
                <TabsList
                  aria-label="Run details"
                  className="w-max min-w-full flex-nowrap [contain:none]"
                >
                  <TabsTrigger value="work">What ARIA did</TabsTrigger>
                  <TabsTrigger value="evidence">Evidence ({evidence.length})</TabsTrigger>
                  <TabsTrigger value="logs">Logs</TabsTrigger>
                  <TabsTrigger value="history">History</TabsTrigger>
                </TabsList>
              </div>
              <TabsContent value="work" className="grid gap-6">
                <TabNote>
                  Each part of ARIA in turn: what it read, what it found and what it decided.
                </TabNote>
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
                        {/* Nothing when the run's own pause or end closes the stream: the page
                            announces that, and "ended" sounded like a failure (A10). */}
                        {timeline.state === "live"
                          ? "Live: following the triage as it happens."
                          : timeline.state === "reconnecting"
                            ? "Reconnecting to the live updates."
                            : timeline.state === "error"
                              ? "Live updates stopped. This page still checks for progress every few seconds."
                              : timeline.state === "closed"
                                ? ""
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
              <TabsContent value="evidence" className="grid gap-4">
                <TabNote>
                  Everything the report may cite. Each statement in the report points to the
                  evidence it rests on, such as E3.
                </TabNote>
                {evidence.length ? (
                  <EvidenceTable evidence={evidence} cited={cited} />
                ) : (
                  <p className="text-sm text-muted-foreground">No evidence yet.</p>
                )}
              </TabsContent>
              <TabsContent value="logs" className="grid gap-4">
                <TabNote>
                  The logs as ARIA read them: lines that differ only in details are grouped into one
                  pattern, with how many lines share it.
                </TabNote>
                {values?.batch ? (
                  <Templates batch={values.batch} />
                ) : (
                  <p className="text-sm text-muted-foreground">
                    The logs have not been parsed yet.
                  </p>
                )}
              </TabsContent>
              <TabsContent value="history" className="grid gap-4">
                {/* History introduces itself: one sentence, not two that say the same (D12). */}
                <History runId={detail.id} viewing={checkpoint} onView={setCheckpoint} />
              </TabsContent>
            </Tabs>
          </div>
        </details>
      </div>
    </EvidenceProvider>
  );
}
