import { ArrowRightIcon, Clock3Icon } from "lucide-react";
import Link from "next/link";

import { LevelChip } from "@/components/aria/severity";
import type { Replay, ReplayClaim, ReplayEvidence } from "@/lib/site-data";
import { cn } from "@/lib/utils";

/**
 * The claim the hero opens on: the first that cites log lines, preferring one that reads as plain
 * English (one quoting a log template, with its "<*>", reads as code at this size).
 */
export function openClaim(
  data: Replay,
): { claim: ReplayClaim; evidence: ReplayEvidence } | undefined {
  const cited = data.claims.flatMap((claim) => {
    const id = claim.evidence.find((e) => (data.evidence[e]?.lines.length ?? 0) > 0);
    const evidence = id ? data.evidence[id] : undefined;
    return evidence ? [{ claim, evidence }] : [];
  });
  // Best of all, a claim that doesn't already quote its line, so the line below adds something.
  const quotes = (c: (typeof cited)[number]) =>
    c.claim.text.includes(citedLine(data, c.evidence).text.slice(0, 24));
  const plain = cited.filter((c) => !c.claim.text.includes("<*>"));
  return plain.find((c) => !quotes(c)) ?? plain[0] ?? cited[0];
}

/** The log line a citation points at: from the recorded window when it is shown there, else the
 * evidence's own example. */
function citedLine(data: Replay, evidence: ReplayEvidence): { lineNo?: number; text: string } {
  const shown = data.lines.find((l) => !l.quarantined && evidence.lines.includes(l.lineNo));
  if (shown) return { lineNo: shown.lineNo, text: shown.text };
  return { lineNo: evidence.lines[0], text: evidence.detail.replace(/^example:\s*/, "") };
}

/** The recorded run's report, opened on one claim and the log line it cites (item 27). */
function ReportCard({ data }: { data: Replay }) {
  const open = openClaim(data);
  const line = open ? citedLine(data, open.evidence) : undefined;
  const p = Math.round((data.probabilities[data.severity] ?? 0) * 100);
  // The other levels it could not rule out, said plainly: "short list" is explained further down.
  const others = data.predictionSet.filter((level) => level !== data.severity);
  const moreClaims = data.claims.length - 1;
  return (
    <figure className="hero-rise grid gap-3">
      <div className="grid gap-5 rounded-[12px] bg-raised p-5 sm:p-6">
        <div className="grid gap-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <LevelChip severity={data.severity} />
            <span className="text-xs text-muted-foreground">
              {p}% likely
              {others.length ? `. Could also be ${others.join(" or ")}` : ""}
            </span>
          </div>
          <p className="text-lg leading-snug tracking-heading text-heading">{data.title}</p>
        </div>
        {open && line ? (
          <div className="grid gap-3 border-t border-rule pt-5">
            <p className="text-sm leading-relaxed text-foreground">
              {open.claim.text}{" "}
              <span className="rounded-full bg-primary px-2 py-0.5 font-mono text-xs text-primary-foreground">
                {open.evidence.id}
              </span>
            </p>
            <div className="grid gap-1 rounded-md bg-sunken px-3 py-2.5">
              <span className="text-xs text-muted-foreground">
                {open.evidence.id} cites{" "}
                {line.lineNo != null ? `log line ${line.lineNo}` : "the log"}
                {open.evidence.lines.length > 1
                  ? `, one of ${open.evidence.lines.length} like it`
                  : ""}
              </span>
              <code className="font-mono text-xs leading-relaxed break-all text-foreground">
                {line.text}
              </code>
            </div>
            {moreClaims > 0 ? (
              <p className="text-xs text-muted-foreground">
                {moreClaims} more {moreClaims === 1 ? "claim" : "claims"}, each with its sources
              </p>
            ) : null}
          </div>
        ) : null}
        {/* A status, not a button: the visitor approves nothing here. */}
        <p className="flex items-center gap-2 border-t border-rule pt-4 text-sm text-muted-foreground">
          <Clock3Icon aria-hidden className="size-4 shrink-0" strokeWidth={1.75} />
          Waiting for a person to approve. Nothing has been sent.
        </p>
      </div>
      <figcaption className="px-1 text-xs leading-relaxed text-heading/80 dark:text-muted-foreground">
        From a recorded run
        {data.model ? ` with ${data.model.service}` : ""}: {data.nLines} real log lines from a
        Hadoop file system (HDFS) in the public Loghub collection, arranged into an incident.
      </figcaption>
    </figure>
  );
}

const PROOF: { title: string; body: string; href: string; link: string }[] = [
  {
    title: "Tested on public, labelled logs",
    body: "Each test pits ARIA against a simpler method, and says where the simpler one wins.",
    href: "/console/evals",
    link: "See the test results",
  },
  {
    title: "Every claim cites a log line",
    body: "A check rejects any sentence whose source is missing or whose numbers disagree with it.",
    href: "#run",
    link: "See an example",
  },
  {
    title: "Nothing is sent without you",
    body: "Messages for chat or a status page wait as drafts until a person approves them.",
    href: "#how-4",
    link: "See the review step",
  },
];

/** Three claims a visitor can check, each linking to its proof. */
function ProofTiles() {
  return (
    <ul className="grid gap-3 md:grid-cols-3">
      {PROOF.map((tile) => (
        <li
          key={tile.title}
          className="grid content-start gap-2 rounded-card border border-rule bg-raised p-6"
        >
          <h2 className="text-base font-medium text-heading">{tile.title}</h2>
          <p className="text-sm leading-relaxed text-muted-foreground">{tile.body}</p>
          <Link
            href={tile.href as never}
            prefetch={false}
            className="mt-1 inline-flex w-fit items-center gap-1.5 text-sm font-medium text-heading underline decoration-control underline-offset-4 hover:decoration-heading"
          >
            {tile.link}
            <ArrowRightIcon aria-hidden className="size-4" />
          </Link>
        </li>
      ))}
    </ul>
  );
}

/** The first screen: the outcome on sage, the way in beneath it, the report on slate, and the
 * three claims a visitor can check. */
export function Hero({ data }: { data: Replay }) {
  return (
    <section
      aria-labelledby="hero-title"
      className="mx-auto grid max-w-[75rem] gap-3 px-3 pt-20 sm:px-6 sm:pt-24"
    >
      <div className="grid gap-3 xl:grid-cols-[minmax(0,11fr)_minmax(0,13fr)]">
        <div className="grid grid-rows-[1fr_auto] gap-3">
          <div className="flex flex-col rounded-card bg-panel-sage p-7 sm:p-10">
            <h1 id="hero-title" className="text-hero max-w-[15ch]">
              Turn a wall of logs into a report you can check.
            </h1>
            <p className="mt-8 max-w-[46ch] text-[0.9375rem] leading-relaxed text-heading xl:mt-auto xl:pt-14">
              For the person on call: ARIA reads an alert&apos;s logs, rates how serious it is,
              finds what happened before, and drafts the report and the messages.
            </p>
          </div>
          <Link
            href="/console/runs/new?source=bigdata"
            prefetch={false}
            className="group/button flex h-16 items-center justify-between rounded-card bg-primary px-7 text-[0.9375rem] font-medium text-primary-foreground transition-colors duration-(--duration-quick) hover:bg-primary-hover sm:h-[4.75rem]"
          >
            Try it on real logs
            <ArrowRightIcon
              aria-hidden
              strokeWidth={1.5}
              className="size-6 transition-transform duration-(--duration-moderate) ease-(--ease-out) group-hover/button:translate-x-1"
            />
          </Link>
        </div>
        <div className={cn("grid content-center rounded-card bg-panel-slate p-4 sm:p-8 lg:p-10")}>
          <ReportCard data={data} />
        </div>
      </div>
      <ProofTiles />
    </section>
  );
}
