"use client";

import { LibraryIcon, SearchIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useDeferredValue, useEffect, useId, useMemo, useState } from "react";

import { SeverityDot } from "@/components/aria/severity";
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
import { useIncidents, useSettingsView } from "@/lib/api/hooks";
import { isSeverity, type IncidentOut } from "@/lib/api/types";
import { failureName } from "@/lib/failure-modes";
import { capitalise, plainResolution, relativeTime, stripSeverity } from "@/lib/format";
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
  return capitalise([systemName(incident.system), count].filter(Boolean).join(", "));
}

/**
 * Entries that tell the same story (system, title, fix and source) as one, counting all their
 * sightings: the seeded library holds the same sample incident more than once.
 */
export function oneOfEach(incidents: IncidentOut[]): IncidentOut[] {
  const seenAs = new Map<string, IncidentOut>();
  for (const incident of incidents) {
    const key = [
      incident.system,
      stripSeverity(incident.title),
      incident.resolution,
      incident.source,
    ].join("\u0000");
    const first = seenAs.get(key);
    if (!first) {
      seenAs.set(key, incident);
      continue;
    }
    const lasts = [first.last_seen, incident.last_seen].filter((when): when is string => !!when);
    seenAs.set(key, {
      ...first,
      occurrences: Math.max(1, first.occurrences) + Math.max(1, incident.occurrences),
      last_seen: lasts.sort().at(-1) ?? null,
    });
  }
  return [...seenAs.values()];
}

// Where a library entry came from, in the words "Seen before" uses on the incident page.
const SOURCE_WORDS: Record<string, string> = {
  curated: "built from a sample",
  memory: "from the library",
};

/** What ARIA remembers: past incidents it searches when a new one comes in. */
export function Memory() {
  const id = useId();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  // The search lives in the address, so Back, a reload or a shared link finds it again (FL-04).
  const [query, setQuery] = useState(() => params.get("q") ?? "");
  const [system, setSystem] = useState(() => params.get("system") ?? "all");
  useEffect(() => {
    const later = window.setTimeout(() => {
      const next = new URLSearchParams(params.toString());
      if (query.trim()) next.set("q", query.trim());
      else next.delete("q");
      if (system !== "all") next.set("system", system);
      else next.delete("system");
      const qs = next.toString();
      if (qs !== params.toString()) {
        router.replace((qs ? `${pathname}?${qs}` : pathname) as never, { scroll: false });
      }
    }, 400);
    return () => window.clearTimeout(later);
  }, [query, system, params, pathname, router]);
  const [limit, setLimit] = useState(PAGE);
  const deferred = useDeferredValue(query.trim());
  const searching = deferred.length >= 2;
  const incidents = useIncidents(
    searching ? deferred : undefined,
    system === "all" ? undefined : system,
  );
  const all = useIncidents();
  // On a shared demo, what a visitor publishes stays theirs: it never joins this library.
  // Unknown until the settings load: neither sentence is said before then (FL-17).
  const shared = useSettingsView().data?.visitor_scope;
  const systems = useMemo(
    () => [...new Set((all.data ?? []).map((i) => i.system))].sort(),
    [all.data],
  );
  const shown = useMemo(() => oneOfEach(incidents.data ?? []), [incidents.data]);
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
        description={`Past incidents ARIA searches when a new one comes in, by keyword and by meaning.${
          shared === undefined
            ? ""
            : shared
              ? " On this shared demo, the incidents you publish stay yours and don't join it."
              : " Each published report adds one."
        }`}
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
                placeholder="For example: disk, quorum, brute force"
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
          Seed it with <code>aria seed</code>, or publish a report: every approved incident is
          remembered.
        </EmptyState>
      ) : (
        <>
          {/* While a new search loads, the last results stay on screen; the count waits for the
              new ones, so it never announces the old list under the new words (RQ-p10). */}
          <p className="text-sm text-muted-foreground" aria-live="polite">
            {incidents.isPlaceholderData
              ? "Searching…"
              : `${
                  searching
                    ? shown.length === 0
                      ? `No incident matches "${deferred}"`
                      : shown.length === 1
                        ? `The closest incident to "${deferred}", by keyword and by meaning`
                        : `The ${shown.length} closest incidents to "${deferred}", by keyword and by meaning, closest first`
                    : shown.length === 1
                      ? "The most recent incident"
                      : `The ${shown.length} most recent incidents`
                }${kinds}.`}
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
                      <SeverityDot
                        severity={isSeverity(incident.severity) ? incident.severity : null}
                      />
                      {/* At least 12rem before the date and tag wrap below, so a phone never
                          squeezes the title to a word per line. */}
                      <span className="min-w-48 flex-1 font-medium wrap-anywhere">
                        {stripSeverity(incident.title)}
                      </span>
                      <span className="text-xs text-muted-foreground">{seen(incident)}</span>
                      {tag(incident) ? (
                        <span className="text-xs text-muted-foreground">{tag(incident)}</span>
                      ) : null}
                    </summary>
                    <div className="grid gap-3 border-t border-rule px-4 py-3 text-sm">
                      <p>{incident.summary}</p>
                      <p>
                        <span className="font-medium">Resolution: </span>
                        <span className="text-muted-foreground">
                          {plainResolution(incident.resolution)}
                        </span>
                      </p>
                      <p className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-faint">
                        <span>{failureName(incident.failure_mode)}</span>
                        {incident.source === "run" && incident.incident_id.startsWith("inc-") ? (
                          // An approved incident's entry is named after its run: inc-X came from run-X.
                          <Link
                            href={
                              `/console/runs/run-${encodeURIComponent(incident.incident_id.slice(4))}` as never
                            }
                            className="text-foreground underline decoration-control underline-offset-2"
                          >
                            from an approved incident: open it
                          </Link>
                        ) : (
                          <>
                            <span>
                              {SOURCE_WORDS[incident.source] ?? `source ${incident.source}`}
                            </span>
                            <span className="font-mono">{incident.incident_id}</span>
                          </>
                        )}
                        {incident.runbook_slug ? (
                          <Link
                            href={
                              `/console/runbooks/${encodeURIComponent(incident.runbook_slug)}` as never
                            }
                            className="text-foreground underline decoration-control underline-offset-2"
                          >
                            open its runbook
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
