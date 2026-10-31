"use client";

import { LoaderCircleIcon, PlayIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useId, useRef, useState } from "react";
import { toast } from "sonner";

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
import { cn } from "@/lib/utils";

// New triage's samples: real Loghub lines arranged into incidents, built on the server. Visitors
// pick where the logs come from first (the choice stays in the address, so Back and sharing
// work), then a sample, then run it. Each card offers a size only where it changes the result.

const SOURCES = [
  { key: "security", name: "Security and sign-ins" },
  { key: "web", name: "Web and cloud" },
  { key: "bigdata", name: "Big-data clusters" },
  { key: "hpc", name: "Supercomputers" },
  { key: "noise", name: "False alarms" },
] as const;
type Source = (typeof SOURCES)[number]["key"] | "all";
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
              "inline-flex h-8 cursor-pointer items-center rounded-sm px-3 text-sm ring-1 ring-rule ring-inset has-focus-visible:ring-2 has-focus-visible:ring-foreground",
              value === option.value
                ? "bg-foreground text-background ring-foreground"
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

function RealLines({ lines }: { lines: string[] }) {
  if (!lines.length) return null;
  return (
    <details className="group text-sm">
      <summary className="w-fit cursor-pointer text-muted-foreground hover:text-heading">
        Show {lines.length} real {lines.length === 1 ? "line" : "lines"}
      </summary>
      <pre
        tabIndex={0}
        role="region"
        aria-label="Real lines from this sample"
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

  return (
    <li className="flex flex-col gap-3 rounded-lg bg-raised p-5">
      <div className="grid gap-1">
        <h3 className="font-sans text-base leading-snug font-semibold text-heading">
          {sample.title}
        </h3>
        <p className="text-xs text-muted-foreground">
          {sample.technology}
          {sample.benign ? ", needs no action" : ""}
          {sample.tricky ? ", one line tries to trick ARIA" : ""}
        </p>
      </div>
      <p className="text-sm text-muted-foreground">{sample.summary}</p>
      {compact && sample.id === RECORDED ? (
        <Link href="/#run" className="w-fit text-sm underline underline-offset-4">
          Watch the recorded run
        </Link>
      ) : null}
      {compact ? null : <RealLines lines={sample.preview ?? []} />}
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
          <Button asChild size="sm" variant="ghost">
            <Link href="/#run">Watch the recorded run</Link>
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
    <li className="flex flex-col gap-3 rounded-lg bg-raised p-5 ring-1 ring-primary/40 ring-inset">
      <div className="grid gap-1">
        <p className="text-xs font-medium text-primary">Real logs</p>
        <h3 className="font-sans text-base leading-snug font-semibold text-heading">
          {incident.title}
        </h3>
      </div>
      <p className="text-sm text-muted-foreground">{incident.summary}</p>
      <p className="text-xs text-muted-foreground">
        {incident.lines.toLocaleString("en")} real lines, and the label experts gave each{" "}
        {incident.unit}, which ARIA never sees.
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

function SourceFilter({
  current,
  counts,
  real,
}: {
  current: Source;
  counts: Record<string, number>;
  real: number;
}) {
  const params = useSearchParams();
  const pathname = usePathname();
  const href = (key: Source) => {
    const next = new URLSearchParams(params.toString());
    if (key === "all") next.delete("source");
    else next.set("source", key);
    const qs = next.toString();
    return `${pathname}${qs ? `?${qs}` : ""}`;
  };
  const all = Object.values(counts).reduce((a, b) => a + b, 0) + real;
  const chips: { key: Source; name: string; count: string }[] = [
    { key: "all", name: "All", count: String(all) },
    ...SOURCES.map((s) => ({
      key: s.key,
      name: s.name,
      count:
        s.key === "bigdata" && real
          ? `${counts[s.key] ?? 0} + ${real} real`
          : String(counts[s.key] ?? 0),
    })),
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
                  ? "bg-foreground text-background ring-foreground"
                  : "text-heading hover:bg-sunken",
              )}
            >
              {chip.name}
              <span
                className={cn(
                  "tabular",
                  current === chip.key ? "opacity-80" : "text-muted-foreground",
                )}
              >
                {chip.count}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function SampleGallery() {
  const scenarios = useScenarios();
  const real = useRealIncidents();
  const params = useSearchParams();
  const raw = params.get("source");
  const source: Source = isSource(raw) ? raw : "all";
  const [showAll, setShowAll] = useState<Source | null>(null);

  if (scenarios.isPending) {
    return (
      <div className="grid gap-4" aria-busy="true" aria-label="Loading the samples">
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

  const counts: Record<string, number> = {};
  for (const s of samples) counts[s.source] = (counts[s.source] ?? 0) + 1;
  const headline = samples.filter((s) => s.headline);
  // Under "All", the cards featured above are not repeated; a chosen source lists all of its own.
  const featured = new Set(headline.map((s) => s.id));
  const listed =
    source === "all"
      ? samples.filter((s) => !featured.has(s.id))
      : samples.filter((s) => s.source === source);
  const listedReals =
    source === "all" ? reals.slice(1) : source === "bigdata" ? reals : ([] as RealIncident[]);
  const total = listed.length + listedReals.length;
  const expanded = showAll === source || total <= FIRST;
  const cards = expanded ? listed : listed.slice(0, Math.max(0, FIRST - listedReals.length));
  const hidden = total - cards.length - listedReals.length;

  return (
    <div className="grid gap-12">
      {headline.length || reals.length ? (
        <section aria-labelledby="start-title" className="grid gap-4">
          <h2 id="start-title" className="text-xl tracking-heading">
            Start with one of these
          </h2>
          <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {reals.slice(0, 1).map((incident) => (
              <RealIncidentCard key={incident.id} incident={incident} />
            ))}
            {headline.map((sample) => (
              <SampleCard key={sample.id} sample={sample} compact />
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="browse-title" className="grid gap-5">
        <div className="grid gap-2">
          <h2 id="browse-title" className="text-xl tracking-heading">
            Where do the logs come from?
          </h2>
          <p className="max-w-prose text-sm text-muted-foreground">
            Every sample is made of real lines from Loghub&rsquo;s public logs, arranged into an
            incident. Runs from samples are marked as samples, and each waits for your review.
          </p>
        </div>
        <SourceFilter current={source} counts={counts} real={reals.length} />
        <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {listedReals.map((incident) => (
            <RealIncidentCard key={incident.id} incident={incident} />
          ))}
          {cards.map((sample) => (
            <SampleCard key={sample.id} sample={sample} />
          ))}
        </ul>
        {hidden > 0 ? (
          <Button className="justify-self-start" onClick={() => setShowAll(source)}>
            Show {hidden} more
          </Button>
        ) : null}
      </section>
    </div>
  );
}
