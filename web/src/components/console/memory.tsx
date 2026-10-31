"use client";

import { LibraryIcon, SearchIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useDeferredValue, useEffect, useId, useMemo, useRef, useState } from "react";

import { SeverityDot } from "@/components/aria/severity";
import {
  LibrarySkeleton,
  LibraryTiles,
  MostSeen,
  OverTime,
  RankedBars,
  SeverityMix,
} from "@/components/console/library-charts";
import { focusFilters, LibraryFilters } from "@/components/console/library-filters";
import { EmptyState, ErrorState, PageHeader, SectionHeader } from "@/components/console/states";
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
import { useIncidentSearch, useLibrary, useSettingsView } from "@/lib/api/hooks";
import { isSeverity, type IncidentOut } from "@/lib/api/types";
import { failureName } from "@/lib/failure-modes";
import { capitalise, plainResolution, plural, relativeTime, stripSeverity } from "@/lib/format";
import {
  activeDimensions,
  cleared,
  FILTER_LABELS,
  loosenAdvice,
  loosenings,
  matches,
  mergeEntries,
  mostSeen,
  NO_FILTERS,
  readFilters,
  readSort,
  severityBars,
  SORT_NAMES,
  sortEntries,
  summarise,
  timeline,
  toggled,
  topBars,
  withFilters,
  type Dimension,
  type Filters,
  type ListDimension,
  type SortKey,
} from "@/lib/library";
import { systemName } from "@/lib/systems";

const PAGE = 20;
/** A search lists this many of the closest incidents that pass the filters. */
const CLOSEST = 20;

/** "HDFS, seen 3 times, last 2 days ago"; a single sighting is not counted. */
function seen(incident: IncidentOut): string {
  const when = incident.last_seen ? relativeTime(incident.last_seen) : "";
  const count =
    incident.occurrences > 1
      ? `seen ${incident.occurrences} times${when ? `, last ${when}` : ""}`
      : when
        ? `seen ${when}`
        : "";
  // A system's name keeps its own spelling ("macOS"); a line without one starts with a capital.
  const system = systemName(incident.system);
  return system ? [system, count].filter(Boolean).join(", ") : capitalise(count);
}

/**
 * Entries that tell the same story (system, title, fix and source) as one, counting all their
 * sightings: the seeded library holds the same sample incident more than once.
 */
export function oneOfEach(incidents: IncidentOut[]): IncidentOut[] {
  return mergeEntries(incidents).map((entry) => entry.incident);
}

/** Where an incident sits in the list, so a chart can open it there. */
export const incidentAnchor = (id: string) => `incident-${id}`;

// Where a library entry came from, in the words "Seen before" uses on the incident page.
const SOURCE_WORDS: Record<string, string> = {
  curated: "built from a sample",
  memory: "from the library",
};

const SORTED: Record<SortKey, string> = {
  recent: "most recent first",
  seen: "most seen first",
  serious: "most serious first",
  closest: "closest first",
};

/** The incident a link to `#incident-…` points at, when the page opens on one. */
function linkedIncident(): { id: string } | null {
  if (typeof window === "undefined") return null;
  const hash = window.location.hash;
  return hash.startsWith("#incident-") ? { id: decodeURIComponent(hash.slice(10)) } : null;
}

/**
 * What ARIA remembers: past incidents it searches when a new one comes in. Filters narrow the whole
 * page; the figures and charts sum up the incidents that match, and the list below can be searched
 * by meaning and put in order.
 */
export function Memory() {
  const id = useId();
  const params = useSearchParams();
  const pathname = usePathname();
  const filters = useMemo(() => readFilters(params), [params]);
  // The search lives in the address, so Back, a reload or a shared link finds it again (FL-04).
  const [query, setQuery] = useState(() => params.get("q") ?? "");
  useEffect(() => {
    const later = window.setTimeout(() => {
      const next = new URLSearchParams(params.toString());
      if (query.trim()) next.set("q", query.trim());
      else next.delete("q");
      const qs = next.toString();
      if (qs !== params.toString()) {
        window.history.replaceState(null, "", qs ? `${pathname}?${qs}` : pathname);
      }
    }, 400);
    return () => window.clearTimeout(later);
  }, [query, params, pathname]);
  // Back and Forward bring their own search back into the box.
  useEffect(() => {
    const back = () => setQuery(new URLSearchParams(window.location.search).get("q") ?? "");
    window.addEventListener("popstate", back);
    return () => window.removeEventListener("popstate", back);
  }, []);
  const [limit, setLimit] = useState(PAGE);
  const deferred = useDeferredValue(query.trim());
  const searching = deferred.length >= 2;
  const sort = readSort(params, searching);
  const library = useLibrary();
  const search = useIncidentSearch(searching ? deferred : "");
  // On a shared demo, what a visitor publishes stays theirs: it never joins this library.
  // Unknown until the settings load: neither sentence is said before then (FL-17).
  const shared = useSettingsView().data?.visitor_scope;

  const entries = useMemo(() => mergeEntries(library.data?.incidents ?? []), [library.data]);
  const everyIncident = useMemo(() => entries.map((entry) => entry.incident), [entries]);
  const matching = useMemo(
    () => entries.filter((entry) => matches(entry.incident, filters)),
    [entries, filters],
  );
  const hits = useMemo(
    () => (searching ? mergeEntries(search.data ?? []) : []),
    [searching, search.data],
  );
  const list = useMemo(
    () =>
      searching
        ? sortEntries(
            hits.filter((entry) => matches(entry.incident, filters)).slice(0, CLOSEST),
            sort,
          )
        : sortEntries(matching, sort),
    [searching, hits, matching, filters, sort],
  );
  const on = activeDimensions(filters);
  const filtered = on.length > 0;
  const scoped = (own: Dimension) => on.some((dimension) => dimension !== own);

  // Each filter and order is a step Back can undo, like the incident list's (FL-05). The address
  // changes without a trip to the server: everything here is already loaded.
  const go = (next: { filters?: Filters; sort?: SortKey }) => {
    const address = new URLSearchParams(withFilters(params, next.filters ?? filters));
    if (next.sort) {
      if (next.sort === (searching ? "closest" : "recent")) address.delete("sort");
      else address.set("sort", next.sort);
    }
    const qs = address.toString();
    window.history.pushState(null, "", qs ? `${pathname}?${qs}` : pathname);
    setLimit(PAGE);
  };
  const toggle = (dimension: ListDimension) => (value: string) =>
    go({ filters: toggled(filters, dimension, value) });

  // A chart's incident opens in the list: shown, unfolded, in view and focused.
  const [reveal, setReveal] = useState(linkedIncident);
  const revealed = useRef<{ id: string } | null>(null);
  const revealAt = reveal
    ? list.findIndex((entry) => entry.incident.incident_id === reveal.id)
    : -1;
  const shown = Math.max(limit, revealAt + 1);
  useEffect(() => {
    if (!reveal || revealed.current === reveal) return;
    const details = document.getElementById(incidentAnchor(reveal.id));
    if (!(details instanceof HTMLDetailsElement)) return;
    revealed.current = reveal;
    details.open = true;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    details.scrollIntoView({ block: "center", behavior: still ? "auto" : "smooth" });
    details.querySelector("summary")?.focus({ preventScroll: true });
  }, [reveal, shown, list]);
  const open = (incidentId: string) => {
    // A search that left it out gives way, so the incident is there to open.
    if (searching && !list.some((entry) => entry.incident.incident_id === incidentId)) {
      setQuery("");
    }
    setReveal({ id: incidentId });
  };

  const synthetic = list.filter((entry) => entry.incident.synthetic).length;
  // Tag the rarer kind, so a seeded library does not repeat "from a sample" on nearly every row.
  const tagRuns = synthetic > list.length / 2;
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
      : synthetic === list.length
        ? "; all were built from ARIA's samples, not taken from real history"
        : tagRuns
          ? `; ${list.length - synthetic} came from approved incidents, tagged so, and the rest were built from samples`
          : `; ${synthetic} were built from samples, tagged so`;
  const among = filtered ? ", among those that match your filters" : "";
  const summaryLine = searching
    ? list.length === 1
      ? `The closest incident to "${deferred}", by keyword and by meaning${among}`
      : `The ${list.length} closest incidents to "${deferred}", by keyword and by meaning${among}, ${SORTED[sort]}`
    : `${plural(list.length, "incident")} ${
        filtered
          ? list.length === 1
            ? "matches your filters"
            : "match your filters"
          : "in the library"
      }, ${SORTED[sort]}`;

  const severity = severityBars(entries, filters);
  const systems = topBars(entries, filters, "system");
  const kindsOfFailure = topBars(entries, filters, "kind");
  const repeats = mostSeen(matching);
  const line = timeline(matching);
  // The charts that have something to show, two to a row on a wide screen; an odd one out at the
  // end takes the whole row rather than leave a hole beside it.
  const halves = [
    "severity",
    ...(systems.bars.length > 1 ? ["system"] : []),
    ...(repeats.length > 0 ? ["seen"] : []),
    ...(kindsOfFailure.bars.length > 1 ? ["kind"] : []),
  ];
  const span = (chart: string) =>
    halves.length % 2 === 1 && halves.at(-1) === chart ? "@4xl:col-span-2" : undefined;

  const loadedLibrary = library.data;
  return (
    <div className="grid gap-8">
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
        {loadedLibrary && entries.length > 0 ? (
          <LibraryFilters
            library={everyIncident}
            filters={filters}
            onChange={(next) => go({ filters: next })}
          />
        ) : null}
      </PageHeader>

      {library.isPending ? (
        <LibrarySkeleton label="Loading the incident library" />
      ) : !loadedLibrary ? (
        <ErrorState
          title="The incident library could not be loaded"
          error={library.error}
          onRetry={() => void library.refetch()}
        />
      ) : entries.length === 0 ? (
        <EmptyState icon={LibraryIcon} title="The incident library is empty">
          Seed it with <code>aria seed</code>, or publish a report: every approved incident is
          remembered.
        </EmptyState>
      ) : matching.length === 0 ? (
        <div aria-live="polite" className="grid">
          <NoMatch
            everyIncident={everyIncident}
            filters={filters}
            onChange={(next) => go({ filters: next })}
          />
        </div>
      ) : (
        <>
          <section aria-labelledby={`${id}-glance`} className="grid gap-6">
            <SectionHeader
              id={`${id}-glance`}
              title="At a glance"
              description={`${
                filtered ? "The incidents that match your filters" : "What the library holds"
              }. Press a level or a bar to filter by it.`}
            />
            <LibraryTiles summary={summarise(matching)} filtered={filtered} />
            {loadedLibrary.complete ? null : (
              <p className="text-sm text-muted-foreground">
                The library holds more incidents than the console reads at once: these figures cover
                the{" "}
                {plural(loadedLibrary.incidents.length, "most recent entry", "most recent entries")}
                .
              </p>
            )}
            <div className="@container">
              <div className="grid gap-6 @4xl:grid-cols-2">
                <SeverityMix
                  set={severity}
                  scoped={scoped("severity")}
                  onToggle={toggle("severity")}
                  className={span("severity")}
                />
                {systems.bars.length > 1 ? (
                  <RankedBars
                    dimension="system"
                    set={systems}
                    scoped={scoped("system")}
                    onToggle={toggle("system")}
                    className={span("system")}
                  />
                ) : null}
                {repeats.length > 0 ? (
                  <MostSeen
                    repeats={repeats}
                    scoped={filtered}
                    anchor={incidentAnchor}
                    onOpen={open}
                    className={span("seen")}
                  />
                ) : null}
                {kindsOfFailure.bars.length > 1 ? (
                  <RankedBars
                    dimension="kind"
                    set={kindsOfFailure}
                    scoped={scoped("kind")}
                    onToggle={toggle("kind")}
                    className={span("kind")}
                  />
                ) : null}
                {line ? (
                  <OverTime line={line} scoped={filtered} className="@4xl:col-span-2" />
                ) : null}
              </div>
            </div>
          </section>

          <section aria-labelledby={`${id}-find`} className="grid gap-5">
            <SectionHeader
              id={`${id}-find`}
              title="Find a past incident"
              description="Search by keyword and by meaning, or browse in the order you choose. Open one to see how it was fixed."
            />
            <div className="flex flex-wrap items-end gap-3">
              <div className="grid min-w-0 flex-[1_1_16rem] gap-1.5 md:max-w-md">
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
                    onChange={(event) => {
                      setQuery(event.target.value);
                      setLimit(PAGE);
                    }}
                  />
                </div>
              </div>
              <div className="grid w-full gap-1.5 sm:w-52">
                <label htmlFor={`${id}-sort`} className="text-sm font-medium">
                  Sort by
                </label>
                <Select value={sort} onValueChange={(value) => go({ sort: value as SortKey })}>
                  <SelectTrigger id={`${id}-sort`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(searching
                      ? (["closest", "recent", "seen", "serious"] as const)
                      : (["recent", "seen", "serious"] as const)
                    ).map((key) => (
                      <SelectItem key={key} value={key}>
                        {SORT_NAMES[key]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {searching && search.isError && !search.data ? (
              <ErrorState
                title="The incident library could not be searched"
                error={search.error}
                onRetry={() => void search.refetch()}
              />
            ) : (
              <>
                {/* While a new search loads, the last results stay on screen; the count waits for
                    the new ones, so it never announces the old list under the new words (RQ-p10).
                    A search that finds nothing says so once, in the card, which the same live
                    region reads. */}
                <div aria-live="polite" className="grid">
                  {searching && (search.isPending || search.isPlaceholderData) ? (
                    <p className="text-sm text-muted-foreground">Searching…</p>
                  ) : list.length === 0 ? (
                    <EmptyState
                      title={
                        hits.length === 0
                          ? `No past incident matches "${deferred}"`
                          : `No incident close to "${deferred}" matches your filters`
                      }
                      art={<SearchSpot className="h-auto w-full" />}
                      // A long search without spaces still wraps on a phone.
                      className="[&_p]:wrap-anywhere"
                    >
                      {hits.length === 0
                        ? "Try fewer or different words."
                        : (loosenAdvice(
                            hits.map((entry) => entry.incident),
                            filters,
                          ) ?? "Try other words, or clear the filters.")}
                    </EmptyState>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      {summaryLine}
                      {kinds}.
                    </p>
                  )}
                </div>
                {list.length === 0 ? null : (
                  <ul className="grid gap-2">
                    {list.slice(0, shown).map(({ incident }) => (
                      <li key={incident.incident_id}>
                        <details
                          id={incidentAnchor(incident.incident_id)}
                          className="group rounded-lg bg-raised"
                        >
                          <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-1 rounded-lg px-4 py-3 [&::-webkit-details-marker]:hidden">
                            <SeverityDot
                              severity={isSeverity(incident.severity) ? incident.severity : null}
                            />
                            {/* At least 12rem before the date and tag wrap below, so a phone
                                never squeezes the title to a word per line. */}
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
                              {incident.source === "run" &&
                              incident.incident_id.startsWith("inc-") ? (
                                // An approved incident's entry is named after its run: inc-X came
                                // from run-X.
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
                {list.length > shown ? (
                  <div className="flex flex-wrap items-center gap-3">
                    <Button size="sm" variant="secondary" onClick={() => setLimit(shown + PAGE)}>
                      Show {Math.min(PAGE, list.length - shown)} more
                    </Button>
                    <span className="text-sm text-muted-foreground">
                      {shown} of {list.length} shown
                    </span>
                  </div>
                ) : null}
              </>
            )}
          </section>
        </>
      )}
    </div>
  );
}

/** Nothing matches: say which filter to loosen, and offer to. */
function NoMatch({
  everyIncident,
  filters,
  onChange,
}: {
  everyIncident: IncidentOut[];
  filters: Filters;
  onChange: (next: Filters) => void;
}) {
  const best = loosenings(everyIncident, filters)[0];
  return (
    <EmptyState
      title="No incident matches these filters"
      art={<SearchSpot className="h-auto w-full" />}
      action={
        <div className="flex flex-wrap gap-2">
          {best && best.count > 0 ? (
            <Button
              size="sm"
              variant="primary"
              onClick={() => {
                onChange(cleared(filters, best.dimension));
                focusFilters();
              }}
            >
              Clear “{FILTER_LABELS[best.dimension]}”
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="secondary"
            onClick={() => {
              onChange(NO_FILTERS);
              focusFilters();
            }}
          >
            Clear all filters
          </Button>
        </div>
      }
    >
      {loosenAdvice(everyIncident, filters) ??
        "No one filter is to blame: together they leave nothing. Clear them to start again."}
    </EmptyState>
  );
}
