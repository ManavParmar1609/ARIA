"use client";

import { LibraryIcon, SearchIcon } from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useId, useMemo, useState } from "react";

import { SeverityBadge } from "@/components/aria/severity";
import { EmptyState, ErrorState, LoadingRows, PageHeader } from "@/components/console/states";
import { SearchSpot } from "@/components/illustrations/spots";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useIncidents } from "@/lib/api/hooks";
import { isSeverity, type IncidentOut } from "@/lib/api/types";
import { relativeTime, stripSeverity } from "@/lib/format";
import { systemName } from "@/lib/systems";

const PAGE = 20;

/** "HDFS, seen 3 times, last 2 days ago"; a single sighting is not counted. */
function seen(incident: IncidentOut): string {
  const when = incident.last_seen ? relativeTime(incident.last_seen) : "";
  const count =
    incident.occurrences > 1
      ? `seen ${incident.occurrences} times${when ? `, last ${when}` : ""}`
      : when
        ? `seen ${when}`
        : "";
  return [systemName(incident.system), count].filter(Boolean).join(", ");
}

/** What ARIA remembers: past incidents it searches when a new one comes in. */
export function Memory() {
  const id = useId();
  const [query, setQuery] = useState("");
  const [system, setSystem] = useState("all");
  const [limit, setLimit] = useState(PAGE);
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
  // Tag the rarer kind, so a seeded library does not repeat "from a sample" on nearly every row.
  const tagRuns = synthetic > shown.length / 2;
  const tag = (incident: IncidentOut) =>
    tagRuns
      ? incident.synthetic
        ? null
        : "from an approved incident"
      : incident.synthetic
        ? "from a sample"
        : null;
  const kinds =
    synthetic === 0
      ? ""
      : synthetic === shown.length
        ? "; all were built from ARIA's samples, not taken from real history"
        : tagRuns
          ? `; ${shown.length - synthetic} came from approved incidents, tagged so, and the rest were built from samples`
          : `; ${synthetic} were built from samples, tagged so`;

  return (
    <div className="grid gap-6">
      <PageHeader
        title="Incident library"
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
                onChange={(e) => {
                  setQuery(e.target.value);
                  setLimit(PAGE);
                }}
              />
            </div>
          </div>
          <div className="grid w-48 gap-1.5">
            <label htmlFor={`${id}-system`} className="text-sm font-medium">
              System
            </label>
            <Select
              value={system}
              onValueChange={(value) => {
                setSystem(value);
                setLimit(PAGE);
              }}
            >
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
        <LoadingRows rows={6} label="Loading the incident library" />
      ) : incidents.isError ? (
        <ErrorState
          title="The incident library could not be searched"
          error={incidents.error}
          onRetry={() => void incidents.refetch()}
        />
      ) : !searching && system === "all" && shown.length === 0 ? (
        <EmptyState icon={LibraryIcon} title="The incident library is empty">
          Seed it with <code>aria seed</code>, or publish a report: every approved run is
          remembered.
        </EmptyState>
      ) : (
        <>
          <p className="text-sm text-muted-foreground" aria-live="polite">
            {searching
              ? `The ${shown.length} closest incidents to "${deferred}", by keyword and by meaning, closest first`
              : `The ${shown.length} most recent incidents`}
            {kinds}.
          </p>
          {shown.length === 0 ? (
            <EmptyState
              title="Nothing matches that filter"
              art={<SearchSpot className="h-auto w-full" />}
            >
              Try fewer words, or another system.
            </EmptyState>
          ) : (
            <ul className="grid gap-2">
              {shown.slice(0, limit).map((incident) => (
                <li key={incident.incident_id}>
                  <details className="group rounded-lg bg-raised">
                    <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 [&::-webkit-details-marker]:hidden">
                      <SeverityBadge
                        severity={isSeverity(incident.severity) ? incident.severity : null}
                        size="sm"
                      />
                      {/* At least 12rem before the date and tag wrap below, so a phone never
                          squeezes the title to a word per line. */}
                      <span className="min-w-48 flex-1 font-medium wrap-anywhere">
                        {stripSeverity(incident.title)}
                      </span>
                      <span className="text-xs text-muted-foreground">{seen(incident)}</span>
                      {tag(incident) ? (
                        <span className="rounded-xs border border-rule px-1.5 text-xs text-muted-foreground">
                          {tag(incident)}
                        </span>
                      ) : null}
                    </summary>
                    <div className="grid gap-3 border-t border-rule px-4 py-3 text-sm">
                      <p>{incident.summary}</p>
                      <p>
                        <span className="font-medium">Resolution: </span>
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
          {shown.length > limit ? (
            <div className="flex flex-wrap items-center gap-3">
              <Button size="sm" variant="secondary" onClick={() => setLimit(limit + PAGE)}>
                Show {Math.min(PAGE, shown.length - limit)} more
              </Button>
              <span className="text-sm text-muted-foreground">
                {limit} of {shown.length} shown
              </span>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
