"use client";

import { useQuery } from "@tanstack/react-query";
import { InboxIcon, PlusIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

import { SeverityDot } from "@/components/aria/severity";
import { runTitle } from "@/components/console/run-row";
import { EmptyState, ErrorState, LoadingRows, PageHeader } from "@/components/console/states";
import { AllClearSpot, SearchSpot } from "@/components/illustrations/spots";
import { ExampleStatus, RunStatus } from "@/components/console/status";
import { decidedByLabel } from "@/lib/decision";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiFetch } from "@/lib/api/client";
import { useRuns } from "@/lib/api/hooks";
import {
  isSeverity,
  type RunPage,
  type RunStatus as Status,
  type RunSummary,
} from "@/lib/api/types";
import { absoluteTime, relativeTime } from "@/lib/format";
import { systemName, triggerLabel } from "@/lib/systems";

const FILTERS: { value: Status | "all"; label: string }[] = [
  { value: "all", label: "All incidents" },
  { value: "awaiting_review", label: "Waiting for review" },
  { value: "running", label: "Running" },
  { value: "published", label: "Published" },
  { value: "rejected", label: "Discarded" },
  { value: "failed", label: "Failed" },
];

const EMPTY: Record<string, string> = {
  all: "No incidents yet. Pick a sample to triage, or paste your own logs.",
  awaiting_review: "Nothing is waiting for review.",
  running: "Nothing is running right now.",
  published: "No published reports yet.",
  rejected: "No discarded drafts.",
  failed: "No failed triages.",
};

function usePages(status: Status | "all") {
  // How many pages are shown, not where each began: every check fetches them again in turn, each
  // from where the one before it ends now, so incidents that arrive while older ones are open
  // push the list down instead of opening a gap between two pages.
  const [count, setCount] = useState(1);
  const [key, setKey] = useState(status);
  if (key !== status) {
    setKey(status);
    setCount(1);
  }
  const query = useQuery({
    queryKey: ["runs", "queue", status, count],
    queryFn: async () => {
      const runs: RunSummary[] = [];
      let before: string | null = null;
      for (let page = 0; page < count; page += 1) {
        const params = new URLSearchParams({ limit: "50" });
        if (status !== "all") params.set("status", status);
        if (before) params.set("before", before);
        const result = await apiFetch<RunPage>(`/api/v1/runs?${params.toString()}`);
        runs.push(...result.runs);
        before = result.next_before ?? null;
        if (!before) break;
      }
      const seen = new Set<string>();
      return { runs: runs.filter((run) => !seen.has(run.id) && seen.add(run.id)), next: before };
    },
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  });
  const more = () => {
    if (query.data?.next) setCount((current) => current + 1);
  };
  return { ...query, more };
}

/** Who settled the level. "Needs your call" holds only while the run waits for this person: an
 * example every visitor reads waits for nobody's call (RQ-p7). */
function decider(run: RunSummary): string {
  if (run.decided_by !== "fallback") return decidedByLabel(run.decided_by);
  if (run.status === "published") return "Confirmed by a reviewer";
  if (run.status === "rejected" || run.example) return "ARIA was unsure";
  return decidedByLabel(run.decided_by);
}

function Decider({ run }: { run: RunSummary }) {
  if (!run.decided_by) return <span className="text-faint">—</span>;
  return <span>{decider(run)}</span>;
}

export function Queue() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const raw = params.get("status") ?? "all";
  const status = (FILTERS.some((f) => f.value === raw) ? raw : "all") as Status | "all";
  const runs = usePages(status);
  // An example waiting for review is a draft every visitor reads, not a task for this one.
  const list = (runs.data?.runs ?? []).filter(
    (run) => status !== "awaiting_review" || !run.example,
  );
  const filterId = useId();
  // After "Load older incidents", focus moves to the first incident it added, so a keyboard
  // continues down the list instead of starting again at the top.
  const firstAdded = useRef<number | null>(null);
  useEffect(() => {
    const index = firstAdded.current;
    if (index == null || list.length <= index) return;
    firstAdded.current = null;
    const links = document.querySelectorAll<HTMLElement>(`[data-run-index="${index}"]`);
    [...links].find((link) => link.offsetParent !== null)?.focus();
  }, [list.length]);
  const loadOlder = () => {
    firstAdded.current = list.length;
    runs.more();
  };

  const setStatus = (value: string) => {
    const next = new URLSearchParams(params.toString());
    if (value === "all") next.delete("status");
    else next.set("status", value);
    const qs = next.toString();
    router.replace((qs ? `${pathname}?${qs}` : pathname) as never, { scroll: false });
  };

  return (
    <div className="grid gap-6">
      <PageHeader
        title="Incidents"
        description="Every incident ARIA has triaged, newest first. Open one to see its evidence, review its report or go back to an earlier step."
        actions={
          <Button asChild variant="primary">
            <Link href="/console/runs/new">
              <PlusIcon aria-hidden />
              New triage
            </Link>
          </Button>
        }
      >
        {/* One quiet control instead of six buttons: the calm budget allows four badges. */}
        <div className="flex items-center gap-2 text-sm">
          <label htmlFor={filterId} className="text-muted-foreground">
            Show
          </label>
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger id={filterId} className="h-9 w-auto min-w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {FILTERS.map((f) => (
                <SelectItem key={f.value} value={f.value}>
                  {f.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </PageHeader>

      {/* Hidden while the list cannot load: a count from before would contradict the error. */}
      {status === "all" && !runs.isError ? (
        <Waiting onShow={() => setStatus("awaiting_review")} />
      ) : null}

      {runs.isPending ? (
        <LoadingRows rows={6} label="Loading incidents" />
      ) : runs.isError ? (
        <ErrorState
          title="Incidents could not be loaded"
          error={runs.error}
          onRetry={() => void runs.refetch()}
        />
      ) : list.length === 0 ? (
        <EmptyState
          icon={InboxIcon}
          art={
            status === "all" ? (
              <AllClearSpot className="h-auto w-full" />
            ) : (
              <SearchSpot className="h-auto w-full" />
            )
          }
          title={EMPTY[status] ?? EMPTY.all ?? ""}
          action={
            status === "all" ? (
              <Button asChild size="sm">
                <Link href="/console/runs/new">Start a triage</Link>
              </Button>
            ) : (
              <Button size="sm" onClick={() => setStatus("all")}>
                Show all incidents
              </Button>
            )
          }
        />
      ) : (
        <>
          {/* the table on wide screens, where its columns leave the incident room; rows below */}
          <div className="hidden xl:block">
            <Table aria-label="Incidents">
              <TableHeader>
                <TableRow>
                  <TableHead className="w-24">Severity</TableHead>
                  <TableHead>Incident</TableHead>
                  <TableHead className="w-36">Status</TableHead>
                  <TableHead className="w-52">How it was rated</TableHead>
                  <TableHead className="w-32 text-right">Started</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.map((run, index) => (
                  <TableRow key={run.id} className="relative hover:bg-raised/60">
                    <TableCell>
                      {/* A dot, as in the incident library: a filled badge on every row, beside a
                          status, made the list a wall of labels. */}
                      <SeverityDot severity={isSeverity(run.severity) ? run.severity : null} />
                    </TableCell>
                    <TableCell className="max-w-0">
                      <Link
                        href={`/console/runs/${encodeURIComponent(run.id)}` as never}
                        title={runTitle(run)}
                        data-run-index={index}
                        className="block truncate font-medium after:absolute after:inset-0 after:content-['']"
                      >
                        {runTitle(run)}
                      </Link>
                      <span className="block truncate text-xs text-muted-foreground">
                        {systemName(run.system)},{" "}
                        {run.example ? "an example every visitor sees" : triggerLabel(run.trigger)}
                        {run.parent_run_id && run.trigger !== "fork" ? ", a copy" : ""}
                      </span>
                    </TableCell>
                    <TableCell>
                      {run.example ? (
                        <ExampleStatus status={run.status} />
                      ) : (
                        <RunStatus status={run.status} />
                      )}
                    </TableCell>
                    <TableCell className="text-sm">
                      <Decider run={run} />
                    </TableCell>
                    <TableCell className="text-right text-sm whitespace-nowrap text-muted-foreground">
                      <time dateTime={run.created_at} title={absoluteTime(run.created_at)}>
                        {relativeTime(run.created_at)}
                      </time>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <ul className="grid gap-2 xl:hidden">
            {list.map((run, index) => (
              <li key={run.id} className="relative rounded-lg bg-raised p-4">
                <div className="flex items-center justify-between gap-2">
                  <SeverityDot severity={isSeverity(run.severity) ? run.severity : null} />
                  {run.example ? (
                    <ExampleStatus status={run.status} />
                  ) : (
                    <RunStatus status={run.status} />
                  )}
                </div>
                <Link
                  href={`/console/runs/${encodeURIComponent(run.id)}` as never}
                  data-run-index={index}
                  className="mt-2 block font-medium wrap-anywhere after:absolute after:inset-0 after:content-['']"
                >
                  {runTitle(run)}
                </Link>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {systemName(run.system)}, {relativeTime(run.created_at)}
                </p>
              </li>
            ))}
          </ul>
          {runs.data?.next ? (
            <Button className="justify-self-start" onClick={loadOlder} disabled={runs.isFetching}>
              {runs.isFetching ? "Loading" : "Load older incidents"}
            </Button>
          ) : null}
        </>
      )}
    </div>
  );
}

/** The incidents waiting for a person, as one line above the list, with a way to show only them. */
/** Marks an incident every visitor of a shared demo sees, which only a copy of one's own changes. */
function Waiting({ onShow }: { onShow: () => void }) {
  const { data, isError } = useRuns("awaiting_review", 50, 30_000);
  // Examples wait for review too, but only on a copy of one's own: they are not "your" review.
  const n = data?.runs.filter((run) => !run.example).length ?? 0;
  if (n === 0 || isError) return null;
  return (
    <p className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-panel-keylime px-4 py-3 text-sm text-heading dark:bg-highlight">
      <span>
        {n >= 50 ? "50 or more incidents are" : n === 1 ? "1 incident is" : `${n} incidents are`}{" "}
        waiting for your review.
      </span>
      <button type="button" onClick={onShow} className="font-medium underline underline-offset-4">
        Show {n === 1 ? "it" : "them"}
      </button>
    </p>
  );
}
