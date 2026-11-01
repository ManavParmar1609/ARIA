"use client";

import { ArrowLeftIcon, ArrowRightIcon, LoaderCircleIcon, PlayIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { toast } from "sonner";

import { TermsIn } from "@/components/aria/term";
import { EmptyState, ErrorState } from "@/components/console/states";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/client";
import {
  type RealIncident,
  useRealIncidents,
  useReplay,
  useScenarios,
  useStartSample,
} from "@/lib/api/hooks";
import type { Scenario, SizeChoice } from "@/lib/api/types";
import { glossaryMentions } from "@/lib/glossary";
import { systemName } from "@/lib/systems";
import { cn } from "@/lib/utils";

// New triage's samples: real Loghub lines arranged into incidents, built on the server. Visitors
// pick the log the incident comes from first (the choice stays in the address, so Back and sharing
// work), then one of that log's issues, then run it. Each card offers a size only where it
// changes the result. A group of logs (?source=security and so on) still lists its issues.

export const SOURCES = [
  { key: "security", name: "Security and sign-ins" },
  { key: "web", name: "Web and cloud" },
  { key: "bigdata", name: "Big-data clusters" },
  { key: "hpc", name: "Supercomputers" },
  { key: "noise", name: "False alarms" },
] as const;
type Source = (typeof SOURCES)[number]["key"] | "all";

// The groups the logs are shown in, and each log in a line someone new to it can read.
const GROUPS = [
  ...SOURCES.filter((s) => s.key !== "noise"),
  { key: "desktop", name: "Phones and computers" },
  { key: "other", name: "Other logs" },
] as const;
type Group = (typeof GROUPS)[number]["key"];

interface DataSource {
  system: string;
  group: Group;
  about: string;
}

const DATA_SOURCES: DataSource[] = [
  { system: "openssh", group: "security", about: "Sign-in attempts on a server's remote login" },
  { system: "linux", group: "security", about: "A Linux server's system and sign-in log" },
  { system: "apache", group: "web", about: "A web server's error log" },
  { system: "openstack", group: "web", about: "A private cloud's servers and disk images" },
  { system: "proxifier", group: "web", about: "A desktop proxy's connection log" },
  { system: "hdfs", group: "bigdata", about: "The storage servers of a Hadoop cluster" },
  { system: "hadoop", group: "bigdata", about: "Jobs running on a Hadoop cluster" },
  {
    system: "zookeeper",
    group: "bigdata",
    about: "The service that keeps a cluster's servers in agreement",
  },
  { system: "bgl", group: "hpc", about: "A supercomputer at Lawrence Livermore" },
  { system: "hpc", group: "hpc", about: "A computing cluster at Los Alamos" },
  { system: "android", group: "desktop", about: "An Android phone's system log" },
  { system: "mac", group: "desktop", about: "A Mac's system log" },
];

/** Every log a sample or a real incident comes from, known ones first, in their groups' order. */
function dataSources(samples: Scenario[], reals: RealIncident[]): DataSource[] {
  const used = new Set([...samples.map((s) => s.system), ...reals.map((r) => r.system)]);
  const known = DATA_SOURCES.filter((d) => used.has(d.system));
  const other = [...used]
    .filter((system) => !DATA_SOURCES.some((d) => d.system === system))
    .map((system): DataSource => ({ system, group: "other", about: "" }));
  return [...known, ...other];
}
const isSource = (value: string | null): value is Source =>
  value === "all" || SOURCES.some((s) => s.key === value);

/** How many cards a source shows before "Show N more". */
const FIRST = 6;
/** The one sample with a recorded run: the landing page plays it, at once. */
const RECORDED = "hdfs.block_serve_exceptions";

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.detail : String(error);
}

function SizePicker({
  choice,
  value,
  onChange,
}: {
  choice: SizeChoice;
  value: number;
  onChange: (value: number) => void;
}) {
  const id = useId();
  return (
    <fieldset className="grid gap-1.5">
      <legend className="text-sm font-medium">{choice.question}</legend>
      <div className="flex flex-wrap gap-1.5">
        {choice.options.map((option) => (
          <label
            key={option.value}
            className={cn(
              // The radio itself is hidden, so its label shows keyboard focus: an outline clear of
              // the fill, visible on the selected choice too.
              "inline-flex h-8 cursor-pointer items-center rounded-sm px-3 text-sm ring-1 ring-rule ring-inset has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-ring",
              value === option.value
                ? "bg-highlight font-medium text-highlight-foreground ring-primary"
                : "text-muted-foreground hover:bg-sunken",
            )}
          >
            <input
              type="radio"
              name={id}
              value={option.value}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
              className="sr-only"
            />
            {option.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function RealLines({ lines, title }: { lines: string[]; title: string }) {
  if (!lines.length) return null;
  return (
    // min-w-0: a long line scrolls inside its box instead of widening the card (RQ-M1).
    <details className="group min-w-0 text-sm">
      <summary className="w-fit cursor-pointer py-0.5 text-muted-foreground hover:text-heading">
        Show {lines.length} real {lines.length === 1 ? "line" : "lines"}
        {/* Each card's control names its sample, so a list of controls tells them apart. */}
        <span className="sr-only"> from {title}</span>
      </summary>
      <pre
        tabIndex={0}
        role="region"
        aria-label={`Real lines from ${title}`}
        className="mt-2 overflow-x-auto rounded-md bg-sunken p-3 font-mono text-xs leading-5"
      >
        {lines.join("\n")}
      </pre>
    </details>
  );
}

function SampleCard({ sample, compact = false }: { sample: Scenario; compact?: boolean }) {
  const router = useRouter();
  const start = useStartSample();
  const starting = useRef(false);
  const [servers, setServers] = useState(sample.servers?.default ?? null);
  const [rate, setRate] = useState(sample.rate?.default ?? null);
  const [started, setStarted] = useState(false);
  const busy = start.isPending || started;

  const run = () => {
    // A double click would start two runs before the first one's state reached the button.
    if (starting.current) return;
    starting.current = true;
    start.mutate(
      {
        id: sample.id,
        body: {
          servers: sample.servers ? servers : null,
          rate: sample.rate ? rate : null,
          options: { use_llm: true, investigate: true, require_approval: true },
        },
      },
      {
        onSuccess: (accepted) => {
          setStarted(true);
          router.push(`/console/runs/${encodeURIComponent(accepted.run_id)}` as never);
        },
        onError: (error) => {
          starting.current = false;
          toast.error("The sample could not be started", { description: errorText(error) });
        },
      },
    );
  };

  // A dotted underline defines the system and its jargon in plain words, once per card.
  const defined = glossaryMentions(sample.technology).map((mention) => mention.key);
  return (
    <li className="flex min-w-0 flex-col gap-3 rounded-lg bg-raised p-5">
      <div className="grid gap-1">
        <h3 className="font-sans text-base leading-snug font-semibold text-heading">
          {sample.title}
        </h3>
        <p className="text-xs text-muted-foreground">
          <TermsIn text={sample.technology} instance={sample.id} />
          {sample.benign ? ", harmless: a test of whether ARIA stays calm" : ""}
          {sample.tricky ? ", one line tries to trick ARIA" : ""}
        </p>
      </div>
      <p className="text-sm text-muted-foreground">
        <TermsIn text={sample.summary} instance={sample.id} skip={defined} />
      </p>
      {compact && sample.id === RECORDED ? (
        <Link
          href="/console/how-it-works/example"
          className="w-fit text-sm underline underline-offset-4"
        >
          Watch its recorded run
        </Link>
      ) : null}
      {compact ? null : <RealLines lines={sample.preview ?? []} title={sample.title} />}
      {!compact && sample.servers && servers != null ? (
        <SizePicker choice={sample.servers} value={servers} onChange={setServers} />
      ) : null}
      {!compact && sample.rate && rate != null ? (
        <SizePicker choice={sample.rate} value={rate} onChange={setRate} />
      ) : null}
      <div className="mt-auto flex flex-wrap items-center gap-2 pt-1">
        <Button
          size="sm"
          onClick={run}
          disabled={busy}
          aria-label={`${busy ? "Starting" : "Run it"}: ${sample.title}`}
        >
          {busy ? (
            <LoaderCircleIcon aria-hidden className="size-4 animate-spin" />
          ) : (
            <PlayIcon aria-hidden />
          )}
          {busy ? "Starting" : "Run it"}
        </Button>
        {sample.id === RECORDED && !compact ? (
          // Long for a button on a narrow phone, so it wraps instead of widening the page.
          <Button
            asChild
            size="sm"
            variant="ghost"
            className="h-auto min-h-8 py-1 whitespace-normal"
          >
            <Link href="/console/how-it-works/example">Watch its recorded run</Link>
          </Button>
        ) : null}
      </div>
    </li>
  );
}

function RealIncidentCard({ incident }: { incident: RealIncident }) {
  const router = useRouter();
  const replay = useReplay();
  const starting = useRef(false);
  const [started, setStarted] = useState(false);
  const busy = replay.isPending || started;
  const run = () => {
    if (starting.current) return;
    starting.current = true;
    replay.mutate(
      {
        id: incident.id,
        body: { options: { use_llm: true, investigate: true, require_approval: true } },
      },
      {
        onSuccess: (accepted) => {
          setStarted(true);
          router.push(`/console/runs/${encodeURIComponent(accepted.run_id)}` as never);
        },
        onError: (error) => {
          starting.current = false;
          toast.error("The replay could not be started", { description: errorText(error) });
        },
      },
    );
  };
  return (
    <li className="flex min-w-0 flex-col gap-3 rounded-lg bg-raised p-5 ring-1 ring-primary/40 ring-inset">
      <div className="grid gap-1">
        <p className="text-xs font-medium text-primary">Real incident</p>
        <h3 className="font-sans text-base leading-snug font-semibold text-heading">
          {incident.title}
        </h3>
      </div>
      <p className="text-sm text-muted-foreground">
        <TermsIn text={incident.summary} instance={incident.id} />
      </p>
      <p className="text-xs text-muted-foreground">
        {incident.lines.toLocaleString("en")} real lines. Experts marked each {incident.unit}{" "}
        healthy or failed: ARIA never sees their verdicts, and the incident compares them with its
        own once it is done.
      </p>
      <div className="mt-auto pt-1">
        <Button
          size="sm"
          onClick={run}
          disabled={busy}
          aria-label={`${busy ? "Starting" : "Replay it"}: ${incident.title}`}
        >
          {busy ? (
            <LoaderCircleIcon aria-hidden className="size-4 animate-spin" />
          ) : (
            <PlayIcon aria-hidden />
          )}
          {busy ? "Starting" : "Replay it"}
        </Button>
      </div>
    </li>
  );
}

function SourceFilter({ current, counts }: { current: Source; counts: Record<Source, number> }) {
  const params = useSearchParams();
  const pathname = usePathname();
  const href = (key: Source) => {
    const next = new URLSearchParams(params.toString());
    if (key === "all") next.delete("source");
    else next.set("source", key);
    const qs = next.toString();
    return `${pathname}${qs ? `?${qs}` : ""}`;
  };
  const chips: { key: Source; name: string }[] = [
    { key: "all", name: "All" },
    ...SOURCES.map((s) => ({ key: s.key, name: s.name })),
  ];
  return (
    <nav aria-label="Where the logs come from">
      <ul className="flex flex-wrap gap-2">
        {chips.map((chip) => (
          <li key={chip.key}>
            <Link
              href={href(chip.key) as never}
              scroll={false}
              aria-current={current === chip.key ? "true" : undefined}
              className={cn(
                "inline-flex h-9 items-center gap-2 rounded-full px-4 text-sm ring-1 ring-rule ring-inset",
                current === chip.key
                  ? "bg-highlight font-medium text-highlight-foreground ring-primary"
                  : "text-heading hover:bg-sunken",
              )}
            >
              {chip.name}
              <span className="tabular text-xs opacity-75">{counts[chip.key]}</span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** The address of New triage with another log chosen (`?log=`), or none. A log has its own
 * parameter: "hpc" names both the supercomputers' group and one cluster's log. */
function useLogHref() {
  const params = useSearchParams();
  const pathname = usePathname();
  return (log: string | null) => {
    const next = new URLSearchParams(params.toString());
    next.delete("source");
    if (log) next.set("log", log);
    else next.delete("log");
    const qs = next.toString();
    return `${pathname}${qs ? `?${qs}` : ""}`;
  };
}

/** Step one: every log an incident can come from, in groups, each with how many issues it has. */
function SourceTiles({ samples, reals }: { samples: Scenario[]; reals: RealIncident[] }) {
  const href = useLogHref();
  const sources = dataSources(samples, reals);
  const count = (system: string) =>
    samples.filter((s) => s.system === system).length +
    reals.filter((r) => r.system === system).length;
  return (
    <section aria-labelledby="sources-title" className="grid gap-6">
      <div className="grid max-w-3xl gap-2">
        <h2
          id="sources-title"
          tabIndex={-1}
          className="font-display text-[1.75rem] leading-tight font-normal tracking-heading"
        >
          Or choose where the logs come from
        </h2>
        <p className="text-lg text-muted-foreground">
          Each is a real, public log. Choose one to see the incidents ARIA can triage in it.
        </p>
      </div>
      {GROUPS.map((group) => {
        const inGroup = sources.filter((d) => d.group === group.key);
        if (!inGroup.length) return null;
        return (
          <div key={group.key} className="grid gap-3">
            <h3 className="text-base text-muted-foreground">{group.name}</h3>
            <ul className="grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {inGroup.map((d) => {
                const n = count(d.system);
                return (
                  <li key={d.system}>
                    <Link
                      href={href(d.system) as never}
                      scroll={false}
                      data-log={d.system}
                      className="group/source grid h-full content-start gap-1.5 rounded-card border border-rule bg-raised p-5 transition-colors duration-(--duration-quick) hover:border-control"
                    >
                      <span className="flex items-baseline justify-between gap-3">
                        <span className="text-lg font-semibold text-heading">
                          {systemName(d.system)}
                        </span>
                        <span className="tabular shrink-0 text-sm text-muted-foreground">
                          {n} {n === 1 ? "issue" : "issues"}
                        </span>
                      </span>
                      {d.about ? (
                        <span className="text-base text-muted-foreground">{d.about}</span>
                      ) : null}
                      <span className="mt-1 inline-flex items-center gap-1 text-sm font-medium text-heading">
                        See its issues
                        <ArrowRightIcon
                          aria-hidden
                          className="size-4 transition-transform duration-(--duration-quick) motion-safe:group-hover/source:translate-x-0.5"
                        />
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </section>
  );
}

/** Step two: one log's issues, each ready to run, and the way back to every log. */
function SourceIssues({
  source,
  samples,
  reals,
}: {
  source: DataSource;
  samples: Scenario[];
  reals: RealIncident[];
}) {
  const href = useLogHref();
  const group = GROUPS.find((g) => g.key === source.group);
  return (
    <section aria-labelledby="issues-title" className="grid gap-6">
      <Link
        href={href(null) as never}
        scroll={false}
        className="inline-flex min-h-6 w-fit items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeftIcon aria-hidden className="size-4" />
        All logs
      </Link>
      <div className="grid max-w-3xl gap-2">
        {group ? <p className="text-sm font-medium text-muted-foreground">{group.name}</p> : null}
        <h2
          id="issues-title"
          tabIndex={-1}
          className="font-display text-[1.75rem] leading-tight font-normal tracking-heading"
        >
          {systemName(source.system)}
        </h2>
        <p className="text-lg text-muted-foreground">
          {source.about ? `${source.about}. ` : ""}Choose an issue: ARIA builds it from real lines
          of this log, works through it while you watch, and waits for your review.
        </p>
      </div>
      <ul className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-2 xl:grid-cols-3">
        {reals.map((incident) => (
          <RealIncidentCard key={incident.id} incident={incident} />
        ))}
        {samples.map((sample) => (
          <SampleCard key={sample.id} sample={sample} />
        ))}
      </ul>
    </section>
  );
}

export function SampleGallery() {
  const scenarios = useScenarios();
  const real = useRealIncidents();
  const params = useSearchParams();
  const raw = params.get("source");
  const source: Source = isSource(raw) ? raw : "all";
  const log = params.get("log");
  const [showAll, setShowAll] = useState<Source | null>(null);
  const list = useRef<HTMLUListElement>(null);
  const revealFrom = useRef<number | null>(null);
  useEffect(() => {
    const index = revealFrom.current;
    if (index == null) return;
    revealFrom.current = null;
    const heading = list.current?.children[index]?.querySelector("h3");
    if (heading instanceof HTMLElement) {
      heading.tabIndex = -1;
      heading.focus();
    }
  });
  // Choosing a log swaps its issues in where the logs were, and "All logs" (or Back) swaps them
  // back. Focus follows: to the issues' heading, or back to the log the person came from, so
  // neither a keyboard nor a screen reader is left at the top of the page. Arriving with a log
  // already chosen leaves focus where the browser puts it.
  const shownLog = useRef(log);
  useEffect(() => {
    const from = shownLog.current;
    if (from === log) return;
    shownLog.current = log;
    const tile = [...document.querySelectorAll<HTMLElement>("[data-log]")].find(
      (link) => link.dataset.log === from,
    );
    const target = log
      ? document.getElementById("issues-title")
      : (tile ?? document.getElementById("sources-title"));
    target?.focus();
  }, [log]);

  // Both lists, or neither: a real incident arriving after the samples would push every card
  // below it down the page.
  if (scenarios.isPending || real.isPending) {
    return (
      <div className="grid gap-4" role="status" aria-busy="true" aria-label="Loading the samples">
        <Skeleton className="h-6 w-56" />
        <div className="grid gap-4 md:grid-cols-3">
          <Skeleton className="h-48" />
          <Skeleton className="h-48" />
          <Skeleton className="h-48" />
        </div>
      </div>
    );
  }
  if (scenarios.isError) {
    return (
      <ErrorState
        title="The samples could not be loaded"
        error={scenarios.error}
        onRetry={() => void scenarios.refetch()}
      />
    );
  }
  const samples = scenarios.data;
  const reals = real.data ?? [];
  if (!samples.length && !reals.length) {
    return (
      <EmptyState title="This server offers no samples">
        Paste your own logs instead: choose the Your own logs tab.
      </EmptyState>
    );
  }

  // How many cards each source holds; the real incidents come from big-data clusters.
  const counts = Object.fromEntries([
    ["all", samples.length + reals.length],
    ...SOURCES.map((s) => [
      s.key,
      samples.filter((sample) => sample.source === s.key).length +
        (s.key === "bigdata" ? reals.length : 0),
    ]),
  ]) as Record<Source, number>;
  const chosen = dataSources(samples, reals).find((d) => d.system === log);
  if (chosen) {
    return (
      <SourceIssues
        source={chosen}
        samples={samples.filter((s) => s.system === chosen.system)}
        reals={reals.filter((r) => r.system === chosen.system)}
      />
    );
  }
  // Every log at once (the default): the quick start, then the logs to choose from.
  const headline = samples.filter((s) => s.headline);
  if (source === "all") {
    return (
      <div className="grid gap-14">
        {headline.length || reals.length ? (
          <section aria-labelledby="start-title" className="grid gap-4">
            <div className="grid max-w-3xl gap-2">
              <h2
                id="start-title"
                className="font-display text-[1.75rem] leading-tight font-normal tracking-heading"
              >
                Start with one of these
              </h2>
              <p className="text-lg text-muted-foreground">
                One click: a real incident, or a sample ARIA handles well.
              </p>
            </div>
            <ul className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-2 xl:grid-cols-4">
              {reals.slice(0, 1).map((incident) => (
                <RealIncidentCard key={incident.id} incident={incident} />
              ))}
              {headline.map((sample) => (
                <SampleCard key={sample.id} sample={sample} compact />
              ))}
            </ul>
          </section>
        ) : null}
        <SourceTiles samples={samples} reals={reals} />
      </div>
    );
  }

  // A group of logs: its issues, a few at first.
  const listed = samples.filter((s) => s.source === source);
  const listedReals = source === "bigdata" ? reals : ([] as RealIncident[]);
  const total = listed.length + listedReals.length;
  const expanded = showAll === source || total <= FIRST;
  const cards = expanded ? listed : listed.slice(0, Math.max(0, FIRST - listedReals.length));
  const hidden = total - cards.length - listedReals.length;

  return (
    <div className="grid gap-12">
      <section aria-labelledby="browse-title" className="grid gap-5">
        <div className="grid gap-2">
          <h2 id="browse-title" className="text-xl tracking-heading">
            Where do the logs come from?
          </h2>
          <p className="max-w-prose text-sm text-muted-foreground">
            Every sample is made of real lines from Loghub&rsquo;s public logs, arranged into an
            incident. Runs from samples are marked as samples, and each waits for your review.
            {listedReals.length
              ? " A real incident replays a cluster’s logs exactly as it wrote them, with the experts’ labels to check ARIA against."
              : ""}
          </p>
        </div>
        <SourceFilter current={source} counts={counts} />
        <ul
          ref={list}
          className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-2 xl:grid-cols-3"
        >
          {listedReals.map((incident) => (
            <RealIncidentCard key={incident.id} incident={incident} />
          ))}
          {cards.map((sample) => (
            <SampleCard key={sample.id} sample={sample} />
          ))}
        </ul>
        {hidden > 0 ? (
          <Button
            className="justify-self-start"
            onClick={() => {
              revealFrom.current = listedReals.length + cards.length;
              setShowAll(source);
            }}
          >
            Show {hidden} more
          </Button>
        ) : null}
      </section>
    </div>
  );
}
