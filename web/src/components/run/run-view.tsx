"use client";

import { CircleHelpIcon, DownloadIcon, HistoryIcon, Trash2Icon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { TagStrip } from "@/components/aria/severity";
import { runTitle } from "@/components/console/run-row";
import { useDocumentTitle } from "@/lib/document-title";
import { EmptyState, ErrorState, LoadingRows } from "@/components/console/states";
import { LostSpot } from "@/components/illustrations/spots";
import { RunStatus } from "@/components/console/status";
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
import { useDeleteRun, useRun, useRunState } from "@/lib/api/hooks";
import { useRunTimeline } from "@/lib/api/stream";
import { isSeverity, type ReviewPrompt, type RunDetail } from "@/lib/api/types";
import { absoluteTime, duration, relativeTime, stripSeverity, writtenOffline } from "@/lib/format";
import { systemName, triggerLabel } from "@/lib/systems";

import { Activity, GraphProgress } from "./activity";
import { Deliveries } from "./deliveries";
import { EvidencePanel, EvidenceProvider } from "./evidence";
import { ExpertCheck } from "./expert-check";
import { History } from "./history";
import { LiveDraft, ReportView } from "./report-view";
import { ReviewPanel } from "./review-panel";
import { EvidenceTable, Similar, Templates } from "./run-tabs";
import { SeverityPanel } from "./severity-panel";
import { AgentTeam } from "./team";

const ACTIVE = new Set(["queued", "running", "awaiting_review"]);

function Header({
  run,
  severity,
  offline,
}: {
  run: RunDetail;
  severity: string | null | undefined;
  /** The deterministic offline provider served the run: its calls are not LLM use. */
  offline: boolean;
}) {
  const sev = isSeverity(severity) ? severity : null;
  const budget = (run.budget ?? {}) as Record<string, unknown>;
  const llmCalls = Number(budget.llm_calls ?? 0);
  return (
    <header className="flex overflow-hidden rounded-lg bg-raised">
      <TagStrip severity={sev} className="w-16 sm:w-20" />
      <div className="grid min-w-0 flex-1 gap-2 p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h1 className="min-w-0 text-xl leading-snug font-medium tracking-heading sm:text-2xl">
            {runTitle(run)}
          </h1>
          <RunStatus status={run.status} />
        </div>
        <p className="text-sm text-muted-foreground">
          {/* A fork says so once, with a link to the run it came from (below). */}
          {systemName(run.system)}, {run.parent_run_id ? "" : `${triggerLabel(run.trigger)}, `}
          <time dateTime={run.created_at} title={absoluteTime(run.created_at)}>
            {relativeTime(run.created_at)}
          </time>
          {run.parent_run_id ? (
            <>
              , forked from{" "}
              <Link
                href={`/console/runs/${encodeURIComponent(run.parent_run_id)}` as never}
                className="underline decoration-control underline-offset-2"
              >
                {run.parent_run_id}
              </Link>
            </>
          ) : null}
        </p>
        <p className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-faint">
          {run.latency_ms != null ? (
            <span>report ready after {duration(run.latency_ms)}</span>
          ) : null}
          <span>
            {llmCalls && !offline
              ? `${llmCalls} model calls, ${((run.tokens_in ?? 0) + (run.tokens_out ?? 0)).toLocaleString("en")} tokens`
              : "offline mode: no LLM"}
          </span>
          {budget.tool_calls ? <span>{String(budget.tool_calls)} tool calls</span> : null}
        </p>
      </div>
    </header>
  );
}

function DeleteRun({ runId }: { runId: string }) {
  const router = useRouter();
  const remove = useDeleteRun();
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
          <DialogTitle>Delete this run?</DialogTitle>
          <DialogDescription>
            The run, its report, events, checkpoints and the incident it added to memory are
            removed. This cannot be undone.
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
            onClick={() =>
              remove.mutate(runId, {
                onSuccess: () => {
                  toast.success("Run deleted");
                  router.push("/console/runs");
                },
              })
            }
          >
            {remove.isPending ? "Deleting" : "Delete the run"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Where the run sits: the incidents list, then this run's ID. */
function Crumbs({ runId }: { runId: string }) {
  return (
    <nav aria-label="Breadcrumb" className="text-sm text-muted-foreground">
      <Link href="/console/runs" className="hover:text-foreground">
        Incidents
      </Link>
      <span aria-hidden className="px-2 text-faint">
        /
      </span>
      <span aria-current="page" className="font-mono text-xs">
        {runId}
      </span>
    </nav>
  );
}

/** The run page's shape while it loads: header, progress rail, report and side panels. */
function RunSkeleton() {
  return (
    <div role="status" className="grid gap-6">
      <span className="sr-only">Loading the run</span>
      <Skeleton className="h-8 w-64 max-w-full" />
      <Skeleton className="h-32 w-full" />
      <div className="grid grid-cols-[repeat(auto-fill,minmax(min(9.5rem,45%),1fr))] gap-1.5">
        {Array.from({ length: 11 }, (_, i) => (
          <Skeleton key={i} className="h-8" />
        ))}
      </div>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_24rem] xl:gap-8">
        <Skeleton className="h-[40rem] w-full" />
        <div className="grid content-start gap-4">
          <Skeleton className="h-[26rem] w-full" />
          <Skeleton className="h-28 w-full" />
        </div>
      </div>
    </div>
  );
}

export function RunView({ runId }: { runId: string }) {
  const run = useRun(runId);
  useDocumentTitle(run.data ? runTitle(run.data) : null);
  const [checkpoint, setCheckpoint] = useState<string | null>(null);
  const [tab, setTab] = useState("team");
  const status = run.data?.status;
  const mode = !run.data ? "off" : ACTIVE.has(run.data.status) ? "live" : "stored";
  const timeline = useRunTimeline(runId, mode);
  // Fetched alongside the run, not after it; a queued run has no state yet.
  const state = useRunState(runId, checkpoint, status !== "queued");
  const values = state.data?.values;
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
  if (run.isError) {
    if (run.error instanceof ApiError && run.error.status === 404) {
      return (
        <EmptyState
          title="This run does not exist"
          art={<LostSpot className="h-auto w-full" />}
          action={
            <Button asChild size="sm">
              <Link href="/console/runs">Back to incidents</Link>
            </Button>
          }
        >
          It may have been deleted, or the link is wrong.
        </EmptyState>
      );
    }
    return (
      <div className="grid gap-6">
        <Crumbs runId={runId} />
        <ErrorState
          title="This run could not be loaded"
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

  const detail = run.data;
  const prompt =
    detail.status === "awaiting_review" ? (detail.review as ReviewPrompt | null) : null;
  const report = values?.report;
  const offline = report ? writtenOffline(report) : false;
  const severity = values?.severity;
  const liveText = timeline.liveText.report ?? "";
  const viewing = checkpoint ? state.data : null;
  const terminal = !ACTIVE.has(detail.status);

  return (
    <EvidenceProvider evidence={evidence} events={events}>
      <div className="grid gap-6">
        <div className="flex min-h-8 flex-wrap items-center justify-between gap-x-3 gap-y-1">
          <Crumbs runId={detail.id} />
          <div className="flex flex-wrap gap-1.5">
            <Button asChild size="sm" variant="ghost">
              <Link href="/console/guide#read-a-run">
                <CircleHelpIcon aria-hidden />
                How to read this
              </Link>
            </Button>
            {detail.report_id ? (
              <>
                <Button asChild size="sm" variant="ghost">
                  <a
                    href={`/api/v1/runs/${encodeURIComponent(detail.id)}/report.md`}
                    download={`${detail.id}-report.md`}
                  >
                    <DownloadIcon aria-hidden />
                    Report
                  </a>
                </Button>
                {detail.status === "published" ? (
                  <Button asChild size="sm" variant="ghost">
                    <a
                      href={`/api/v1/runs/${encodeURIComponent(detail.id)}/postmortem.md`}
                      download={`${detail.id}-postmortem.md`}
                    >
                      <DownloadIcon aria-hidden />
                      Postmortem draft
                    </a>
                  </Button>
                ) : null}
              </>
            ) : null}
            {terminal ? <DeleteRun runId={detail.id} /> : null}
          </div>
        </div>

        <Header run={detail} severity={severity?.severity ?? detail.severity} offline={offline} />

        <GraphProgress events={timeline.events} finalStatus={detail.status} />

        {viewing ? (
          <div
            role="status"
            className="sticky top-14 z-20 flex flex-wrap items-center justify-between gap-3 rounded-lg bg-raised px-4 py-3 text-sm ring-1 ring-primary lg:top-3"
          >
            <span className="flex items-center gap-2">
              <HistoryIcon aria-hidden className="size-4" />
              You are looking at the run as it was at a past checkpoint
              {viewing.next.length ? `, before ${viewing.next.join(" and ")}` : ""}.
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

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_24rem] xl:gap-8">
          <div className="grid min-w-0 content-start gap-6">
            {prompt && !viewing ? (
              <ReviewPanel
                runId={detail.id}
                prompt={prompt}
                actions={values?.actions ?? []}
                report={report}
              />
            ) : null}
            {detail.deliveries?.length && !viewing ? (
              <Deliveries runId={detail.id} deliveries={detail.deliveries} ended={terminal} />
            ) : null}
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
              <EmptyState
                title={detail.status === "queued" ? "Waiting for a worker" : "No report yet"}
              >
                {detail.status === "queued"
                  ? "The run is queued and starts as soon as a worker is free."
                  : "ARIA writes the report after it has rated severity, recalled similar incidents and investigated."}
              </EmptyState>
            )}
            {detail.trigger === "replay" ? <ExpertCheck runId={detail.id} /> : null}
          </div>
          <aside className="grid min-w-0 [scrollbar-width:thin] content-start gap-4 xl:sticky xl:top-6 xl:max-h-[calc(100dvh-3rem)] xl:self-start xl:overflow-y-auto">
            {severity ? (
              <SeverityPanel assessment={severity} />
            ) : (
              <Skeleton className="h-64 w-full" />
            )}
            <EvidencePanel />
          </aside>
        </div>

        <Tabs value={tab} onValueChange={setTab} className="mt-2">
          <TabsList aria-label="Run details">
            <TabsTrigger value="team">How the agents worked</TabsTrigger>
            <TabsTrigger value="activity">Event log</TabsTrigger>
            <TabsTrigger value="evidence">Evidence ({evidence.length})</TabsTrigger>
            <TabsTrigger value="logs">Logs and templates</TabsTrigger>
            <TabsTrigger value="similar">
              Similar incidents ({values?.retrieval?.incidents.length ?? 0})
            </TabsTrigger>
            <TabsTrigger value="history">History and forks</TabsTrigger>
          </TabsList>
          <TabsContent value="team">
            {values ? (
              <AgentTeam values={values} events={timeline.events} />
            ) : (
              <LoadingRows rows={3} label="Loading what the agents did" />
            )}
          </TabsContent>
          <TabsContent value="activity">
            {mode === "live" ? (
              <p className="mb-2 text-xs text-muted-foreground" role="status">
                {timeline.state === "live"
                  ? "Live: following the run as it happens."
                  : timeline.state === "reconnecting"
                    ? "Reconnecting to the run's event stream."
                    : timeline.state === "closed"
                      ? "The run finished."
                      : "Connecting to the run's event stream."}
              </p>
            ) : null}
            <Activity events={timeline.events} offline={offline} titles={messageTitles} />
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
          <TabsContent value="similar">
            {values?.retrieval ? (
              <Similar retrieval={values.retrieval} />
            ) : (
              <p className="text-sm text-muted-foreground">Retrieval has not run yet.</p>
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
