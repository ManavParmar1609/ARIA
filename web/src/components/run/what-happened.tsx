"use client";

import { useMemo } from "react";

import type { LogEvent, ParsedBatch, TemplateStat, TimelineEntry } from "@/lib/api/types";
import { capitalise, clockTime, minutesWords, plainTemplate } from "@/lib/format";

import { Citations, LogLines, LongLine, patternEvidence, useEvidence } from "./evidence";

// "What happened": the facts the logs give, before any judgement. How much there was and over how
// long, the few patterns that carry the incident (each with a real line, and the rest one click
// away), when things happened, and any line the injection guard set aside (items 13 and 17).

const SHOWN = 3;

const plural = (n: number, one: string, many = `${one}s`) =>
  `${n.toLocaleString("en")} ${n === 1 ? one : many}`;

/** "125 lines over 7.7 minutes: 60 errors, on 2 of 48 servers."; a short window's lines come
 * "within a minute", not "over under a minute". */
export function scaleSentence(f: ParsedBatch["features"]): string {
  const when = f.duration_s < 60 ? "within a minute" : `over ${minutesWords(f.duration_s)}`;
  const span = `${plural(f.n_events, "line")} ${when}`;
  const warnings = f.level_counts.WARN ?? 0;
  const what = f.error_events
    ? `${plural(f.error_events, "error")}${warnings ? ` and ${plural(warnings, "warning")}` : ""}`
    : warnings
      ? `no errors, but ${plural(warnings, "warning")}`
      : "no errors or warnings";
  const where =
    f.error_events && f.error_nodes && f.distinct_nodes
      ? `, on ${f.error_nodes} of ${plural(f.distinct_nodes, "server")}`
      : "";
  return `${span}: ${what}${where}.`;
}

/** The patterns that carry the incident first (error-like or new), then the most frequent. */
export function leadingPatterns(templates: TemplateStat[], count = SHOWN): TemplateStat[] {
  const weight = (t: TemplateStat) => (t.error_like ? 2 : 0) + (t.novel ? 1 : 0);
  return [...templates].sort((a, b) => weight(b) - weight(a) || b.count - a.count).slice(0, count);
}

function Pattern({ template, lines }: { template: TemplateStat; lines: LogEvent[] }) {
  const levels = Object.keys(template.levels).join(", ");
  const { byId } = useEvidence();
  // Only the pattern's own evidence: one ARIA kept none for cites nothing, not the window (M3).
  const cites = patternEvidence(template, byId);
  // Each block of lines is named apart from the others: by its evidence, or else by its size.
  const these = `the ${plural(template.count, "line")} like this`;
  const [example, all] = cites.length
    ? [`An example line of ${template.evidence_id}`, `The lines of ${template.evidence_id}`]
    : [`An example of ${these}`, capitalise(these)];
  return (
    <li className="grid gap-1.5">
      {lines.length ? (
        <LogLines lines={lines} limit={1} more={false} label={example} />
      ) : (
        <p className="font-mono text-xs leading-5 wrap-anywhere">
          <LongLine text={plainTemplate(template.template)} />
        </p>
      )}
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="tabular font-medium text-foreground">
          {plural(template.count, "line")} like this
        </span>
        {levels ? <span>{levels}</span> : null}
        {template.nodes > 1 ? <span>on {template.nodes} servers</span> : null}
        {template.novel ? <span>new to this system</span> : null}
        <Citations ids={cites} />
      </p>
      {lines.length > 1 ? (
        <details className="text-xs">
          <summary className="flex min-h-6 w-fit cursor-pointer items-center text-muted-foreground hover:text-heading">
            {lines.length < template.count
              ? `Show ${lines.length} of the ${template.count.toLocaleString("en")} lines`
              : `Show the ${lines.length.toLocaleString("en")} lines`}
          </summary>
          <div className="pt-2">
            <LogLines lines={lines} limit={40} label={all} />
          </div>
        </details>
      ) : null}
    </li>
  );
}

export function WhatHappened({
  batch,
  timeline,
}: {
  batch: ParsedBatch;
  timeline: TimelineEntry[];
}) {
  const byTemplate = useMemo(() => {
    const map = new Map<string, LogEvent[]>();
    for (const e of batch.events ?? []) {
      map.set(e.template_id, [...(map.get(e.template_id) ?? []), e]);
    }
    return map;
  }, [batch.events]);
  const leading = leadingPatterns(batch.templates);
  const rest = batch.templates.length - leading.length;
  const injections = batch.guard?.injections ?? [];
  return (
    <section aria-labelledby="what-title" className="grid gap-5 rounded-lg bg-raised p-5">
      <div className="grid gap-1">
        <h2 id="what-title" className="text-xl">
          What happened in the logs
        </h2>
        <p className="text-base">{scaleSentence(batch.features)}</p>
        <p className="max-w-prose text-sm text-muted-foreground">
          Lines that differ only in details, such as a server name or a number, count as one
          pattern. These stand out: errors and warnings, patterns new to this system, and the ones
          that repeat most.
        </p>
      </div>
      {leading.length ? (
        <div className="grid gap-3">
          <h3 className="text-sm text-muted-foreground">
            {leading.length === 1 ? "The pattern that stands out" : "The patterns that stand out"}
          </h3>
          <ul className="grid gap-4">
            {leading.map((t) => (
              <Pattern
                key={t.template_id}
                template={t}
                lines={byTemplate.get(t.template_id) ?? []}
              />
            ))}
          </ul>
          {rest > 0 ? (
            <p className="text-xs text-muted-foreground">
              {plural(rest, "more pattern")} under Technical details, in Logs.
            </p>
          ) : null}
        </div>
      ) : null}
      {timeline.length ? (
        <details className="text-sm">
          <summary className="w-fit cursor-pointer py-0.5 text-muted-foreground hover:text-heading">
            When it happened ({timeline.length} {timeline.length === 1 ? "moment" : "moments"})
          </summary>
          <ol className="mt-3 grid gap-2 border-l border-rule pl-4">
            {timeline.map((entry, i) => (
              <li key={i} className="relative grid gap-0.5 leading-relaxed">
                <span
                  aria-hidden
                  className="absolute top-2 -left-[1.3rem] block size-2 rounded-full border border-control bg-background"
                />
                {entry.ts ? (
                  <time
                    dateTime={entry.ts}
                    className="tabular font-mono text-xs text-muted-foreground"
                  >
                    {clockTime(entry.ts)}
                  </time>
                ) : null}
                <p>
                  {entry.text} <Citations ids={entry.evidence_ids ?? []} />
                </p>
              </li>
            ))}
          </ol>
        </details>
      ) : null}
      {injections.length ? (
        <p className="rounded-md bg-sev3/12 p-3 text-sm">
          {injections.length === 1
            ? "One line tried to talk ARIA out of the incident."
            : `${injections.length} lines tried to talk ARIA out of the incident.`}{" "}
          ARIA set {injections.length === 1 ? "it" : "them"} aside: left out of the analysis, so{" "}
          {injections.length === 1 ? "it" : "they"} cannot move the rating, and shown to a model
          only as quoted text it is told not to follow. See Logs, below.
        </p>
      ) : null}
    </section>
  );
}
