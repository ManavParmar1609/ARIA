"use client";

import { ChartBarIcon, CheckIcon, TableIcon } from "lucide-react";
import {
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type FocusEvent,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from "react";

import { RollingNumber } from "@/components/aria/rolling-number";
import { SEVERITY_BG } from "@/components/aria/severity";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { isSeverity } from "@/lib/api/types";
import { capitalise, plural, relativeTime, stripSeverity } from "@/lib/format";
import { LEVEL_RESPONSE, LEVEL_WORD } from "@/lib/levels";
import {
  asLabel,
  bucketName,
  kindTitle,
  mostSeenTitle,
  mostSeenTop,
  percent,
  severityTitle,
  systemTitle,
  tiedFirst,
  timelineTitle,
  type Bar,
  type BarSet,
  type LibraryEntry,
  type Summary,
  type Timeline,
} from "@/lib/library";
import { systemName } from "@/lib/systems";
import { cn } from "@/lib/utils";

// The incident library's charts: hand-built HTML on the console's cream cards, so text stays real
// text at any width. Forest ink marks the bars and the severity levels keep their own fills; the
// control grey steps back what a filter leaves out (both checked with the dataviz palette validator,
// light and dark). Every chart has a title that says what it shows, a line on what it counts, a
// tip with exact values on hover and focus, and a table with the same figures.

// --- drawing in ---------------------------------------------------------------------------------

/**
 * A chart's bars draw in once, the first time it comes into view (globals.css: [data-draw]). Only
 * the attribute changes, so later renders keep the bars where they are.
 */
function drawIn(element: HTMLElement | null) {
  if (!element || element.dataset.drawn !== undefined) return;
  if (typeof IntersectionObserver === "undefined") {
    element.dataset.drawn = "";
    return;
  }
  const observer = new IntersectionObserver(
    ([entry]) => {
      if (!entry?.isIntersecting) return;
      element.dataset.drawn = "";
      observer.disconnect();
    },
    { threshold: 0.2 },
  );
  observer.observe(element);
  return () => observer.disconnect();
}

/** The place in a chart's drawing order, which staggers its bars (capped, so none waits long). */
const order = (index: number) => ({ "--i": Math.min(index, 12) }) as CSSProperties;

// --- the tip ------------------------------------------------------------------------------------

interface TipState {
  x: number;
  y: number;
  body: ReactNode;
}

/**
 * One tip per chart, above the bar the pointer or the focus is on. It stays while the pointer rests
 * on it (it sits inside the chart), and Escape or leaving the chart dismisses it (WCAG 1.4.13).
 * Touch skips it: a tap filters at once, and the bar's own words carry its figure.
 */
function useTip() {
  const box = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<TipState | null>(null);
  const show = (anchor: Element, body: ReactNode, clientX?: number) => {
    const outer = box.current?.getBoundingClientRect();
    if (!outer) return;
    const mark = anchor.getBoundingClientRect();
    setTip({
      x: (clientX ?? mark.left + mark.width / 2) - outer.left,
      y: mark.top - outer.top,
      body,
    });
  };
  const hide = () => setTip(null);
  const onPointer = (body: ReactNode) => (event: PointerEvent<HTMLElement>) => {
    if (event.pointerType !== "touch") show(event.currentTarget, body, event.clientX);
  };
  const onFocus = (body: ReactNode) => (event: FocusEvent<HTMLElement>) =>
    show(event.currentTarget, body);
  const area = {
    ref: box,
    onPointerLeave: hide,
    onKeyDown: (event: KeyboardEvent) => {
      if (event.key === "Escape") hide();
    },
    onBlur: (event: FocusEvent<HTMLElement>) => {
      if (!event.currentTarget.contains(event.relatedTarget as Node | null)) hide();
    },
  };
  return { tip, show, onPointer, onFocus, area };
}

function Tip({ tip }: { tip: TipState | null }) {
  const ref = useRef<HTMLDivElement>(null);
  // Kept inside the chart's width, so it never runs off a phone's screen.
  useLayoutEffect(() => {
    const element = ref.current;
    const parent = element?.parentElement;
    if (!element || !parent || !tip) return;
    const half = element.offsetWidth / 2;
    const left = Math.min(Math.max(tip.x, half), parent.clientWidth - half);
    element.style.left = `${left}px`;
  }, [tip]);
  if (!tip) return null;
  return (
    <div
      ref={ref}
      // The same figures are in each bar's name and in the table, so a screen reader is not told
      // them twice.
      aria-hidden
      className="absolute z-20 w-max max-w-64 -translate-x-1/2 -translate-y-full rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground"
      style={{ left: tip.x, top: tip.y - 8 }}
    >
      {tip.body}
    </div>
  );
}

/** The figure first and strongest, then what it is, then what pressing does. */
function TipBody({ value, label, hint }: { value: string; label: string; hint?: string }) {
  return (
    <span className="grid gap-0.5">
      <span className="tabular font-semibold">{value}</span>
      <span className="text-xs opacity-90">{label}</span>
      {hint ? <span className="pt-1 text-xs opacity-90">{hint}</span> : null}
    </span>
  );
}

// --- the card -----------------------------------------------------------------------------------

/** A chart in a cream card: its takeaway as the title, what it counts, and a switch to a table. */
function ChartCard({
  title,
  caption,
  table,
  className,
  children,
}: {
  title: string;
  caption: string;
  table: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  const id = useId();
  const [asTable, setAsTable] = useState(false);
  return (
    <section
      ref={drawIn}
      data-draw=""
      aria-labelledby={`${id}-title`}
      className={cn(
        "@container grid content-start gap-5 rounded-card border border-rule bg-raised p-5 sm:p-6",
        className,
      )}
    >
      <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="grid min-w-0 flex-[1_1_15rem] gap-1.5">
          <h3 id={`${id}-title`} className="text-lg leading-snug wrap-anywhere">
            {title}
          </h3>
          <p className="text-sm text-muted-foreground">{caption}</p>
        </div>
        <button
          type="button"
          onClick={() => setAsTable(!asTable)}
          className="-mx-1.5 inline-flex min-h-8 shrink-0 items-center gap-1.5 rounded-sm px-1.5 text-sm font-medium text-heading underline decoration-control underline-offset-4 hover:decoration-heading"
        >
          {asTable ? (
            <ChartBarIcon aria-hidden className="size-4" />
          ) : (
            <TableIcon aria-hidden className="size-4" />
          )}
          {asTable ? "Show as a chart" : "Show as a table"}
          <span className="sr-only">: {title}</span>
        </button>
      </header>
      {asTable ? table : children}
    </section>
  );
}

function FigureTable({
  label,
  columns,
  rows,
}: {
  label: string;
  columns: string[];
  rows: { key: string; cells: ReactNode[] }[];
}) {
  return (
    <Table aria-label={label}>
      <TableHeader>
        <TableRow>
          {columns.map((column, index) => (
            <TableHead key={column} className={index > 0 ? "text-right" : undefined}>
              {column}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.key}>
            {row.cells.map((cell, index) =>
              index === 0 ? (
                <TableHead key={index} scope="row">
                  {cell}
                </TableHead>
              ) : (
                <TableCell key={index} className="tabular text-right">
                  {cell}
                </TableCell>
              ),
            )}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

// --- the headline figures -----------------------------------------------------------------------

/** Four figures on a keylime panel: how many incidents, sightings and systems, and how many have a
 * runbook. Each rolls into place the first time it comes into view. */
export function LibraryTiles({ summary, filtered }: { summary: Summary; filtered: boolean }) {
  const tiles: { value: string; label: string; share?: number }[] = [
    {
      value: summary.incidents.toLocaleString("en"),
      label: filtered
        ? summary.incidents === 1
          ? "incident matches your filters"
          : "incidents match your filters"
        : summary.incidents === 1
          ? "incident in the library"
          : "incidents in the library",
    },
    {
      value: summary.sightings.toLocaleString("en"),
      label: summary.sightings === 1 ? "sighting" : "sightings, repeats included",
    },
    {
      value: summary.systems.toLocaleString("en"),
      label: summary.systems === 1 ? "system covered" : "systems covered",
    },
    {
      value: percent(summary.withRunbook),
      label: "have a runbook to follow",
      share: summary.withRunbook,
    },
  ];
  return (
    <dl
      ref={drawIn}
      data-draw=""
      className="grid grid-cols-2 gap-x-6 gap-y-8 rounded-card bg-panel-keylime px-6 py-7 sm:px-8 lg:grid-cols-4"
    >
      {tiles.map((tile) => (
        <div key={tile.label} className="grid content-start gap-2.5">
          <dt className="order-2 text-sm text-muted-foreground">{tile.label}</dt>
          <dd className="stat order-1 text-[2.5rem] whitespace-nowrap sm:text-5xl">
            <RollingNumber value={tile.value} />
          </dd>
          {tile.share !== undefined ? (
            // The share as a meter: forest on a mint track, a step down the same greens.
            <dd aria-hidden className="order-3 h-1.5 overflow-hidden rounded-full bg-panel-mint">
              <span
                className="draw-x block h-full rounded-full bg-accent-ink"
                style={{ width: `${tile.share * 100}%` }}
              />
            </dd>
          ) : null}
        </div>
      ))}
    </dl>
  );
}

// --- severity -----------------------------------------------------------------------------------

const firstSentence = (text: string) => text.split(". ")[0]?.replace(/\.$/, "") ?? text;

/**
 * The mix of levels: one strip split by level (the levels' own fills, 2 px apart), and under it a
 * row per level that filters by it. Each row says its level in words, so no level rests on colour.
 */
export function SeverityMix({
  set,
  scoped,
  onToggle,
  className,
}: {
  set: BarSet;
  scoped: boolean;
  onToggle: (level: string) => void;
  className?: string;
}) {
  const { tip, onPointer, onFocus, area } = useTip();
  const some = set.chosen.length > 0;
  const shown = set.bars.filter((bar) => bar.count > 0);
  const hint = (bar: Bar) =>
    bar.chosen
      ? `Press to stop filtering by ${bar.value}`
      : some
        ? `Press to add ${bar.value} to the filter`
        : `Press to show only ${bar.value}`;
  const body = (bar: Bar) => (
    <TipBody
      value={`${plural(bar.count, "incident")} · ${percent(bar.share)}`}
      label={`${bar.value} · ${isSeverity(bar.value) ? LEVEL_WORD[bar.value] : ""}`}
      hint={hint(bar)}
    />
  );
  return (
    <ChartCard
      className={className}
      title={severityTitle(set)}
      caption={
        scoped
          ? "The incidents that match your other filters, by severity level."
          : "Every incident in the library, by its severity level."
      }
      table={
        <FigureTable
          label="Incidents by severity level"
          columns={["Level", "Incidents", "Share"]}
          rows={set.bars.map((bar) => ({
            key: bar.value,
            cells: [
              `${bar.value}, ${isSeverity(bar.value) ? LEVEL_WORD[bar.value] : ""}`,
              bar.count,
              percent(bar.share),
            ],
          }))}
        />
      }
    >
      <div {...area} className="relative grid gap-3">
        {/* The strip is for the pointer; the rows below do the same for keys and screen readers. */}
        <div className="flex h-6 items-center gap-0.5">
          {shown.map((bar, index) => (
            <button
              key={bar.value}
              type="button"
              tabIndex={-1}
              aria-hidden
              onClick={() => onToggle(bar.value)}
              onPointerEnter={onPointer(body(bar))}
              className="group/segment flex h-full min-w-1 items-center"
              style={{ flex: `${bar.count} 1 0` }}
            >
              <span
                className={cn(
                  "draw-x block h-3 w-full transition-opacity duration-(--duration-quick) group-hover/segment:opacity-80",
                  isSeverity(bar.value) && SEVERITY_BG[bar.value],
                  index === 0 && "rounded-l-full",
                  index === shown.length - 1 && "rounded-r-full",
                  some && !bar.chosen && "opacity-30",
                )}
                style={order(index)}
              />
            </button>
          ))}
        </div>
        <ul className="grid gap-0.5">
          {set.bars.map((bar) => (
            <li key={bar.value}>
              <button
                type="button"
                aria-pressed={bar.chosen}
                onClick={() => onToggle(bar.value)}
                onPointerEnter={onPointer(body(bar))}
                onFocus={onFocus(body(bar))}
                className={cn(
                  "flex w-full items-baseline gap-3 rounded-md px-3 py-2.5 text-left text-sm transition-colors duration-(--duration-quick)",
                  bar.chosen ? "bg-highlight text-highlight-foreground" : "hover:bg-sunken",
                )}
              >
                <span
                  aria-hidden
                  className={cn(
                    "mt-1 block size-3 shrink-0 translate-y-px self-start rounded-full border border-sev-edge",
                    isSeverity(bar.value) && SEVERITY_BG[bar.value],
                    some && !bar.chosen && "opacity-30",
                  )}
                />
                <span className="grid min-w-0 gap-0.5">
                  <span>
                    <span className="font-semibold">{bar.value}</span>{" "}
                    <span className="text-muted-foreground">
                      {isSeverity(bar.value) ? LEVEL_WORD[bar.value] : ""}
                    </span>
                  </span>{" "}
                  {/* What the level means, so a newcomer can read the mix without a glossary. */}
                  <span className="text-xs text-muted-foreground">
                    {isSeverity(bar.value) ? firstSentence(LEVEL_RESPONSE[bar.value]) : ""}
                  </span>
                </span>{" "}
                <span className="tabular ml-auto font-medium">
                  {bar.count}
                  <span className="sr-only"> {bar.count === 1 ? "incident" : "incidents"},</span>
                </span>{" "}
                <span className="tabular w-10 text-right text-muted-foreground">
                  {percent(bar.share)}
                </span>
                <span aria-hidden className="flex w-4 justify-center">
                  {bar.chosen ? <CheckIcon className="size-4" strokeWidth={2.25} /> : null}
                </span>
              </button>
            </li>
          ))}
        </ul>
        <Tip tip={tip} />
      </div>
    </ChartCard>
  );
}

// --- bars by system or kind of failure ----------------------------------------------------------

/**
 * Ranked bars, one per system (or kind of failure), each filtering by its value; the bars a filter
 * leaves out turn grey, so they can be added. The rest are summed in a line of their own, without a
 * bar: a bar for many small values together would dwarf the ones it is ranked beside.
 */
export function RankedBars({
  dimension,
  set,
  scoped,
  onToggle,
  className,
}: {
  dimension: "system" | "kind";
  set: BarSet;
  scoped: boolean;
  onToggle: (value: string) => void;
  className?: string;
}) {
  const { tip, onPointer, onFocus, area } = useTip();
  const some = set.chosen.length > 0;
  const ranked = set.bars.filter((bar) => !bar.members);
  const rest = set.bars.find((bar) => bar.members);
  const max = Math.max(1, ...ranked.map((bar) => bar.count));
  const what = dimension === "system" ? "system" : "kind of failure";
  // System names are proper names ("macOS"); a kind of failure starts a label with a capital.
  const label = (name: string) => (dimension === "system" ? name : asLabel(name));
  const body = (bar: Bar) => (
    <TipBody
      value={`${plural(bar.count, "incident")} · ${percent(bar.share)}`}
      label={
        bar.members
          ? bar.members.map((member) => `${label(member.name)} ${member.count}`).join(", ")
          : label(bar.name)
      }
      hint={
        bar.members
          ? `Choose any of these in the ${what} list above`
          : bar.chosen
            ? "Press to stop filtering by it"
            : some
              ? "Press to add it to the filter"
              : "Press to show only these"
      }
    />
  );
  const everyValue = set.bars.flatMap((bar) => bar.members ?? [bar]);
  // The label column narrows on a phone, so each bar stays on its name's line.
  const row =
    "grid w-full grid-cols-[minmax(0,6.5rem)_minmax(0,1fr)] items-center gap-x-3 rounded-md px-3 py-2 text-left @md:grid-cols-[minmax(0,11rem)_minmax(0,1fr)] @md:gap-x-4";
  return (
    <ChartCard
      className={className}
      title={dimension === "system" ? systemTitle(set) : kindTitle(set)}
      caption={
        dimension === "system"
          ? scoped
            ? "The incidents that match your other filters, by the system that logged them."
            : "Every incident in the library, by the system that logged it."
          : scoped
            ? "The incidents that match your other filters, by kind of failure."
            : "Every incident in the library, by its kind of failure."
      }
      table={
        <FigureTable
          label={dimension === "system" ? "Incidents by system" : "Incidents by kind of failure"}
          columns={[dimension === "system" ? "System" : "Kind of failure", "Incidents", "Share"]}
          rows={everyValue.map((bar) => ({
            key: bar.value,
            cells: [label(bar.name), bar.count, percent(set.total ? bar.count / set.total : 0)],
          }))}
        />
      }
    >
      <div {...area} className="relative grid gap-1">
        <ul className="grid gap-0.5">
          {ranked.map((bar, index) => (
            <li key={bar.value}>
              <button
                type="button"
                aria-pressed={bar.chosen}
                onClick={() => onToggle(bar.value)}
                onPointerEnter={onPointer(body(bar))}
                onFocus={onFocus(body(bar))}
                className={cn(
                  row,
                  "transition-colors duration-(--duration-quick)",
                  bar.chosen ? "bg-highlight text-highlight-foreground" : "hover:bg-sunken",
                )}
              >
                <span className="flex min-w-0 items-center gap-1.5 text-sm">
                  {bar.chosen ? (
                    <CheckIcon aria-hidden className="size-4 shrink-0" strokeWidth={2.25} />
                  ) : null}
                  <span className="min-w-0 text-pretty">{label(bar.name)}</span>
                </span>{" "}
                <span className="flex max-w-xl items-center gap-2.5">
                  <span
                    aria-hidden
                    className={cn(
                      "draw-x block h-3 shrink-0 rounded-r-[4px]",
                      some && !bar.chosen ? "bg-control" : "bg-accent-ink",
                    )}
                    style={{
                      ...order(index),
                      width: `calc((100% - 2.5rem) * ${bar.count / max})`,
                      minWidth: bar.count ? 3 : 0,
                    }}
                  />
                  <span className="tabular text-sm">
                    {bar.count}
                    <span className="sr-only"> {bar.count === 1 ? "incident" : "incidents"}</span>
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
        {rest ? (
          // The rest stand for several values at once, so they are not a filter of their own.
          <p
            onPointerEnter={onPointer(body(rest))}
            className={cn(row, "border-t border-rule pt-3 text-sm text-muted-foreground")}
          >
            <span>{capitalise(rest.name)}</span>{" "}
            <span className="tabular">{plural(rest.count, "incident")} between them</span>
          </p>
        ) : null}
        <Tip tip={tip} />
      </div>
    </ChartCard>
  );
}

// --- the most seen ------------------------------------------------------------------------------

/** The incidents seen most often, ranked; each opens in the list below. */
export function MostSeen({
  repeats,
  scoped,
  anchor,
  onOpen,
  className,
}: {
  /** Every incident seen more than once, the most seen first. */
  repeats: LibraryEntry[];
  scoped: boolean;
  anchor: (id: string) => string;
  onOpen: (id: string) => void;
  className?: string;
}) {
  const { tip, onPointer, onFocus, area } = useTip();
  const top = mostSeenTop(repeats);
  const tied = tiedFirst(repeats);
  const max = Math.max(1, ...top.map((entry) => entry.incident.occurrences));
  const body = (entry: LibraryEntry) => {
    const incident = entry.incident;
    const when = relativeTime(incident.last_seen);
    return (
      <TipBody
        value={`Seen ${incident.occurrences} times${when ? `, last ${when}` : ""}`}
        label={`${systemName(incident.system)} · ${incident.severity}`}
        hint="Press to open it in the list below"
      />
    );
  };
  return (
    <ChartCard
      className={className}
      title={mostSeenTitle(repeats)}
      caption={`Sightings of ${
        tied > top.length
          ? `${top.length} of the ${tied} incidents`
          : top.length === 1
            ? "the incident"
            : `the ${top.length} incidents`
      } seen most often${scoped ? ", of those that match your filters" : ""}.`}
      table={
        <FigureTable
          label="The incidents seen most often"
          columns={["Incident", "System", "Times seen"]}
          rows={top.map((entry) => ({
            key: entry.incident.incident_id,
            cells: [
              stripSeverity(entry.incident.title),
              systemName(entry.incident.system),
              entry.incident.occurrences,
            ],
          }))}
        />
      }
    >
      <div {...area} className="relative">
        <ol className="grid gap-0.5">
          {top.map((entry, index) => {
            const incident = entry.incident;
            return (
              <li key={incident.incident_id}>
                <a
                  href={`#${anchor(incident.incident_id)}`}
                  onClick={(event) => {
                    if (event.metaKey || event.ctrlKey || event.shiftKey) return;
                    event.preventDefault();
                    onOpen(incident.incident_id);
                  }}
                  onPointerEnter={onPointer(body(entry))}
                  onFocus={onFocus(body(entry))}
                  className="group/seen grid grid-cols-[1.25rem_minmax(0,1fr)] gap-x-2 gap-y-2 rounded-md px-3 py-2.5 transition-colors duration-(--duration-quick) hover:bg-sunken"
                >
                  <span aria-hidden className="tabular text-sm text-muted-foreground">
                    {index + 1}
                  </span>
                  <span className="text-sm font-medium wrap-anywhere text-heading underline decoration-transparent underline-offset-4 group-hover/seen:decoration-control">
                    {stripSeverity(incident.title)}
                  </span>
                  <span className="col-start-2 flex max-w-xl items-center gap-2.5">
                    {/* One incident alone needs no bar: there is nothing to compare it with. */}
                    {top.length > 1 ? (
                      <span
                        aria-hidden
                        className="draw-x block h-1.5 shrink-0 rounded-r-[4px] bg-accent-ink"
                        style={{
                          ...order(index),
                          width: `calc((100% - 5rem) * ${incident.occurrences / max})`,
                        }}
                      />
                    ) : null}
                    <span className="tabular text-xs whitespace-nowrap text-muted-foreground">
                      {incident.occurrences} times
                    </span>
                  </span>
                </a>
              </li>
            );
          })}
        </ol>
        <Tip tip={tip} />
      </div>
    </ChartCard>
  );
}

// --- over time ----------------------------------------------------------------------------------

/**
 * Sightings by day, week or month as columns on one baseline, the peak labelled. With focus, the
 * columns work like a slider: the arrow keys step through them, and a screen reader hears each.
 */
export function OverTime({
  line,
  scoped,
  className,
}: {
  line: Timeline;
  scoped: boolean;
  className?: string;
}) {
  const { tip, show, onPointer, area } = useTip();
  const [active, setActive] = useState<number | null>(null);
  const columns = useRef<(HTMLSpanElement | null)[]>([]);
  const max = Math.max(1, ...line.buckets.map((bucket) => bucket.count));
  const peak = line.buckets.findIndex((bucket) => bucket.count === max);
  const years = new Set(line.buckets.map((bucket) => bucket.start.slice(0, 4))).size > 1;
  const name = (start: string) => bucketName(start, line.unit, years);
  const short = (start: string) =>
    new Date(`${start}T00:00:00Z`).toLocaleDateString("en-GB", {
      ...(line.unit === "month"
        ? { month: "short", year: "numeric" }
        : { day: "numeric", month: "short" }),
      timeZone: "UTC",
    });
  const body = (bucket: Timeline["buckets"][number]) => (
    <TipBody value={plural(bucket.count, "sighting")} label={capitalise(name(bucket.start))} />
  );
  const step = (index: number) => {
    const bounded = Math.min(Math.max(index, 0), line.buckets.length - 1);
    const bucket = line.buckets[bounded];
    const column = columns.current[bounded];
    setActive(bounded);
    if (bucket && column) show(column, body(bucket));
  };
  const at = active ?? peak;
  const current = line.buckets[at];
  // Up to four dates under the axis, evenly spaced and always the first and the last, so a long
  // span can be placed without crowding a phone.
  const count = line.buckets.length;
  const every = Math.max(1, Math.ceil((count - 1) / 3));
  const ticks = line.buckets
    .map((bucket, index) => ({ bucket, index }))
    .filter(
      ({ index }) =>
        index === 0 ||
        index === count - 1 ||
        (index % every === 0 && count - 1 - index >= every / 2),
    );
  return (
    <ChartCard
      className={className}
      title={timelineTitle(line)}
      caption={`${scoped ? "Sightings of the incidents that match your filters" : "Every sighting"}, by the ${line.unit} each was last seen.`}
      table={
        <FigureTable
          label="Sightings over time"
          columns={[capitalise(line.unit), "Sightings"]}
          rows={line.buckets.map((bucket) => ({
            key: bucket.start,
            cells: [capitalise(name(bucket.start)), bucket.count],
          }))}
        />
      }
    >
      <div {...area} className="relative grid gap-2">
        <div
          role="slider"
          aria-label={`Sightings by ${line.unit}`}
          aria-valuemin={0}
          aria-valuemax={line.buckets.length - 1}
          aria-valuenow={at}
          aria-valuetext={
            current
              ? `${capitalise(name(current.start))}: ${plural(current.count, "sighting")}`
              : undefined
          }
          tabIndex={0}
          onFocus={() => step(at)}
          onKeyDown={(event) => {
            const moves: Record<string, number> = {
              ArrowLeft: at - 1,
              ArrowDown: at - 1,
              ArrowRight: at + 1,
              ArrowUp: at + 1,
              Home: 0,
              End: line.buckets.length - 1,
            };
            const to = moves[event.key];
            if (to === undefined) return;
            event.preventDefault();
            step(to);
          }}
          className="flex h-44 items-end gap-0.5 rounded-xs border-b border-rule pt-6"
        >
          {line.buckets.map((bucket, index) => (
            <span
              key={bucket.start}
              ref={(element) => {
                columns.current[index] = element;
              }}
              onPointerEnter={(event) => {
                setActive(index);
                onPointer(body(bucket))(event);
              }}
              className="relative flex h-full min-w-0 flex-1 items-end justify-center"
            >
              {bucket.count > 0 ? (
                <span
                  className={cn(
                    "draw-y relative block w-full max-w-6 rounded-t-[4px] bg-accent-ink",
                    index === active && "outline-2 outline-offset-2 outline-ring",
                  )}
                  style={{ ...order(index), height: `${(bucket.count / max) * 100}%` }}
                >
                  {index === peak ? (
                    <span className="tabular absolute bottom-full left-1/2 mb-1 -translate-x-1/2 text-xs font-medium">
                      {bucket.count}
                    </span>
                  ) : null}
                </span>
              ) : null}
            </span>
          ))}
        </div>
        <div aria-hidden className="tabular relative h-4 text-xs text-muted-foreground">
          {ticks.map(({ bucket, index }) => (
            <span
              key={bucket.start}
              className={cn(
                "absolute top-0 whitespace-nowrap",
                index === 0 ? "" : index === count - 1 ? "-translate-x-full" : "-translate-x-1/2",
              )}
              style={{
                left:
                  index === 0
                    ? 0
                    : index === count - 1
                      ? "100%"
                      : `${((index + 0.5) / count) * 100}%`,
              }}
            >
              {short(bucket.start)}
            </span>
          ))}
        </div>
        <Tip tip={tip} />
      </div>
    </ChartCard>
  );
}

// --- waiting ------------------------------------------------------------------------------------

/** The library's shape while it loads: chips, the four figures, two charts and the list. */
export function LibrarySkeleton({ label }: { label: string }) {
  return (
    <div role="status" aria-live="polite" className="grid gap-8">
      <span className="sr-only">{label}</span>
      <div className="flex flex-wrap gap-2">
        {[28, 24, 30, 24].map((width, index) => (
          <Skeleton key={index} className="h-9 rounded-full" style={{ width: `${width / 4}rem` }} />
        ))}
        <Skeleton className="h-9 w-56" />
        <Skeleton className="h-9 w-64" />
      </div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-8 rounded-card bg-panel-keylime px-6 py-7 sm:px-8 lg:grid-cols-4">
        {[0, 1, 2, 3].map((index) => (
          <div key={index} className="grid gap-3">
            <Skeleton className="h-11 w-20" />
            <Skeleton className="h-4 w-32 max-w-full" />
          </div>
        ))}
      </div>
      <div className="grid gap-6 xl:grid-cols-2">
        <div className="grid content-start gap-5 rounded-card border border-rule bg-raised p-6">
          <Skeleton className="h-5 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-3 w-full rounded-full" />
          {[0, 1, 2, 3].map((index) => (
            <Skeleton key={index} className="h-6 w-full" />
          ))}
        </div>
        <div className="grid content-start gap-5 rounded-card border border-rule bg-raised p-6">
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-4 w-1/2" />
          {[100, 74, 40, 34, 28, 22].map((width, index) => (
            <div key={index} className="grid grid-cols-[6rem_1fr] items-center gap-4">
              <Skeleton className="h-4 w-20" />
              <Skeleton className="h-3" style={{ width: `${width}%` }} />
            </div>
          ))}
        </div>
      </div>
      <div className="grid gap-2">
        {[0, 1, 2, 3].map((index) => (
          <Skeleton key={index} className="h-12 w-full" />
        ))}
      </div>
    </div>
  );
}
