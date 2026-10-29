"use client";

import { LibraryIcon, SearchIcon } from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useId, useMemo, useState } from "react";

import { SeverityBadge } from "@/components/aria/severity";
import { EmptyState, ErrorState, LoadingRows, PageHeader } from "@/components/console/states";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useIncidents } from "@/lib/api/hooks";
import { isSeverity } from "@/lib/api/types";
import { relativeTime } from "@/lib/format";
import { systemName } from "@/lib/systems";

/** What ARIA remembers: past incidents it searches when a new one comes in. */
export function Memory() {
  const id = useId();
  const [query, setQuery] = useState("");
  const [system, setSystem] = useState("all");
  const deferred = useDeferredValue(query.trim());
  const searching = deferred.length >= 2;
  const incidents = useIncidents(
    searching ? deferred : undefined,
    system === "all" ? undefined : system,
  );
  const all = useIncidents();
  const systems = useMemo(
    () => [...new Set((all.data ?? []).map((i) => i.system))].sort(),
    [all.data],
  );
  const shown = incidents.data ?? [];
  const synthetic = shown.filter((i) => i.synthetic).length;

  return (
    <div className="grid gap-6">
      <PageHeader
        title="Incident memory"
        description="Past incidents ARIA searches when a new one comes in, by keyword and by meaning. Each published report adds one."
      >
        <div className="flex flex-wrap items-end gap-3">
          <div className="grid min-w-64 flex-1 gap-1.5 md:max-w-md">
            <label htmlFor={`${id}-q`} className="text-sm font-medium">
              Search
            </label>
            <div className="relative">
              <SearchIcon
                aria-hidden
                className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-faint"
              />
              <Input
                id={`${id}-q`}
                type="search"
                className="pl-9"
                placeholder="disk, quorum, brute force..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
          </div>
          <div className="grid w-48 gap-1.5">
            <label htmlFor={`${id}-system`} className="text-sm font-medium">
              System
            </label>
            <Select value={system} onValueChange={setSystem}>
              <SelectTrigger id={`${id}-system`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All systems</SelectItem>
                {systems.map((s) => (
                  <SelectItem key={s} value={s}>
                    {systemName(s)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </PageHeader>

      {incidents.isPending ? (
        <LoadingRows rows={6} label="Loading incident memory" />
      ) : incidents.isError ? (
        <ErrorState error={incidents.error} onRetry={() => void incidents.refetch()} />
      ) : !searching && system === "all" && shown.length === 0 ? (
        <EmptyState icon={LibraryIcon} title="Incident memory is empty">
          Seed it with <code>aria seed</code>, or publish a report: every approved run is
          remembered.
        </EmptyState>
      ) : (
        <>
          <p className="text-sm text-muted-foreground" aria-live="polite">
            {searching
              ? `The ${shown.length} closest incidents to "${deferred}", by keyword and by meaning, closest first`
              : `The ${shown.length} most recent incidents`}
            {synthetic > 0 ? `; ${synthetic} are synthetic seed incidents, labelled so` : ""}.
          </p>
          {shown.length === 0 ? (
            <EmptyState title="Nothing matches that filter">
              Try fewer words, or another system.
            </EmptyState>
          ) : (
            <ul className="grid gap-2">
              {shown.map((incident) => (
                <li key={incident.incident_id}>
                  <details className="group rounded-lg bg-raised">
                    <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 [&::-webkit-details-marker]:hidden">
                      <SeverityBadge
                        severity={isSeverity(incident.severity) ? incident.severity : null}
                        size="sm"
                      />
                      <span className="min-w-0 flex-1 font-medium">{incident.title}</span>
                      <span className="text-xs text-muted-foreground">
                        {systemName(incident.system)}, seen {incident.occurrences}{" "}
                        {incident.occurrences === 1 ? "time" : "times"}
                        {incident.last_seen ? `, last ${relativeTime(incident.last_seen)}` : ""}
                      </span>
                      {incident.synthetic ? (
                        <span className="rounded-xs border border-rule px-1.5 text-[0.6875rem] text-faint">
                          synthetic
                        </span>
                      ) : null}
                    </summary>
                    <div className="grid gap-3 border-t border-rule px-4 py-3 text-sm">
                      <p>{incident.summary}</p>
                      <p>
                        <span className="font-semibold">Resolution: </span>
                        <span className="text-muted-foreground">{incident.resolution}</span>
                      </p>
                      <p className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-faint">
                        <span>failure mode {incident.failure_mode.replaceAll("_", " ")}</span>
                        <span>source {incident.source}</span>
                        <span className="font-mono">{incident.incident_id}</span>
                        {incident.runbook_slug ? (
                          <Link
                            href={
                              `/console/runbooks/${encodeURIComponent(incident.runbook_slug)}` as never
                            }
                            className="text-foreground underline decoration-control underline-offset-2"
                          >
                            runbook {incident.runbook_slug}
                          </Link>
                        ) : null}
                      </p>
                    </div>
                  </details>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
