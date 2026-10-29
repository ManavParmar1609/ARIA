"use client";

import { useQuery } from "@tanstack/react-query";
import { InboxIcon, PlusIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { SeverityBadge } from "@/components/aria/severity";
import { runTitle } from "@/components/console/run-row";
import { EmptyState, ErrorState, LoadingRows, PageHeader } from "@/components/console/states";
import { AllClearSpot, SearchSpot } from "@/components/illustrations/spots";
import { decidedByLabel, RunStatus } from "@/components/console/status";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiFetch } from "@/lib/api/client";
import {
  isSeverity,
  type RunPage,
  type RunStatus as Status,
  type RunSummary,
} from "@/lib/api/types";
import { absoluteTime, duration, percent, relativeTime } from "@/lib/format";
import { systemName, triggerLabel } from "@/lib/systems";
import { cn } from "@/lib/utils";

const FILTERS: { value: Status | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "awaiting_review", label: "Needs review" },
  { value: "running", label: "Running" },
  { value: "published", label: "Published" },
  { value: "rejected", label: "Rejected" },
  { value: "failed", label: "Failed" },
];

const EMPTY: Record<string, string> = {
  all: "No runs yet. Start one from logs, or point Alertmanager or Grafana at ARIA.",
  awaiting_review: "Nothing is waiting for review.",
  running: "Nothing is running right now.",
  published: "No published reports yet.",
  rejected: "No rejected reports.",
  failed: "No failed runs.",
};

function usePages(status: Status | "all") {
  const [pages, setPages] = useState<string[]>([""]);
  const [key, setKey] = useState(status);
  if (key !== status) {
    setKey(status);
    setPages([""]);
  }
  const query = useQuery({
    queryKey: ["runs", "queue", status, pages],
    queryFn: async () => {
      const results = await Promise.all(
        pages.map((before) => {
          const params = new URLSearchParams({ limit: "50" });
          if (status !== "all") params.set("status", status);
          if (before) params.set("before", before);
          return apiFetch<RunPage>(`/api/v1/runs?${params.toString()}`);
        }),
      );
      return {
        runs: results.flatMap((r) => r.runs),
        next: results.at(-1)?.next_before ?? null,
      };
    },
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  });
  const more = () => {
    const next = query.data?.next;
    if (next) setPages((current) => [...current, next]);
  };
  return { ...query, more };
}

function Confidence({ run }: { run: RunSummary }) {
  if (run.confidence == null) return <span className="text-faint">—</span>;
  return (
    <span className="grid gap-0.5">
      <span>{decidedByLabel(run.decided_by)}</span>
      <span className="tabular text-xs text-muted-foreground">
        {percent(run.confidence)} confident
      </span>
    </span>
  );
}

export function Queue() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const raw = params.get("status") ?? "all";
  const status = (FILTERS.some((f) => f.value === raw) ? raw : "all") as Status | "all";
  const runs = usePages(status);
  const list = runs.data?.runs ?? [];

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
        description="Every triage run, newest first. Open one to see its evidence, review its report or rewind it."
        actions={
          <Button asChild variant="primary">
            <Link href="/console/runs/new">
              <PlusIcon aria-hidden />
              New triage
            </Link>
          </Button>
        }
      >
        <div role="group" aria-label="Filter by status" className="flex flex-wrap gap-1.5">
          {FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              aria-pressed={status === f.value}
              onClick={() => setStatus(f.value)}
              className={cn(
                "h-8 rounded-md border px-3 text-sm transition-colors duration-(--duration-quick)",
                status === f.value
                  ? "border-primary bg-highlight font-medium text-highlight-foreground"
                  : "border-rule text-muted-foreground hover:border-control hover:text-foreground",
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </PageHeader>

      {runs.isPending ? (
        <LoadingRows rows={6} label="Loading incidents" />
      ) : runs.isError ? (
        <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />
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
                Show all runs
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
                  <TableHead className="w-52">Decided by</TableHead>
                  <TableHead className="w-28 text-right">Time to review</TableHead>
                  <TableHead className="w-32 text-right">Started</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.map((run) => (
                  <TableRow key={run.id} className="relative hover:bg-raised/60">
                    <TableCell>
                      <SeverityBadge severity={isSeverity(run.severity) ? run.severity : null} />
                    </TableCell>
                    <TableCell className="max-w-0">
                      <Link
                        href={`/console/runs/${encodeURIComponent(run.id)}` as never}
                        className="block truncate font-medium after:absolute after:inset-0 after:content-['']"
                      >
                        {runTitle(run)}
                      </Link>
                      <span className="block truncate text-xs text-muted-foreground">
                        {systemName(run.system)}, {triggerLabel(run.trigger)}
                        {run.parent_run_id ? ", forked" : ""}
                      </span>
                    </TableCell>
                    <TableCell>
                      <RunStatus status={run.status} />
                    </TableCell>
                    <TableCell className="text-sm">
                      <Confidence run={run} />
                    </TableCell>
                    <TableCell className="tabular text-right text-sm">
                      {duration(run.latency_ms) || <span className="text-faint">—</span>}
                    </TableCell>
                    <TableCell className="text-right text-sm text-muted-foreground">
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
            {list.map((run) => (
              <li key={run.id} className="relative rounded-lg bg-raised p-4">
                <div className="flex items-center justify-between gap-2">
                  <SeverityBadge
                    severity={isSeverity(run.severity) ? run.severity : null}
                    size="sm"
                  />
                  <RunStatus status={run.status} />
                </div>
                <Link
                  href={`/console/runs/${encodeURIComponent(run.id)}` as never}
                  className="mt-2 block font-medium after:absolute after:inset-0 after:content-['']"
                >
                  {runTitle(run)}
                </Link>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {systemName(run.system)}, {relativeTime(run.created_at)}
                  {run.latency_ms != null ? `, review after ${duration(run.latency_ms)}` : ""}
                </p>
              </li>
            ))}
          </ul>
          {runs.data?.next ? (
            <Button className="justify-self-start" onClick={runs.more} disabled={runs.isFetching}>
              {runs.isFetching ? "Loading" : "Load older runs"}
            </Button>
          ) : null}
        </>
      )}
    </div>
  );
}
