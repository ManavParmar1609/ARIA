"use client";

import Link from "next/link";

import { SeverityBadge } from "@/components/aria/severity";
import { CodeText } from "@/components/ui/code-text";
import type { RetrievalResult, SimilarIncident } from "@/lib/api/types";
import { isSeverity } from "@/lib/api/types";
import { plainResolution } from "@/lib/format";
import { systemName } from "@/lib/systems";

import { Citations } from "./evidence";

// "Seen before": the past incidents most like this one and how each was fixed, the runbook to
// follow, and, closed, how ARIA searched (items 13 and 17; it replaces the "Similar incidents"
// tab).

// Where a past incident in the library came from, as the library names it.
const SOURCE: Record<string, string> = {
  curated: "built from a sample",
  run: "from an approved incident",
  memory: "from the library",
};

/**
 * Past incidents of one kind (the same system, failure and fix), closest first. The library keeps
 * several sightings of most kinds and counts them together, so a row each would repeat the same
 * title, count and fix: one row cites them all instead.
 */
export type PastKind = { lead: SimilarIncident; all: SimilarIncident[] };

export function pastKinds(incidents: SimilarIncident[]): PastKind[] {
  const kinds = new Map<string, PastKind>();
  for (const incident of incidents) {
    const key = [incident.system, incident.failure_mode, incident.resolution].join("\u0000");
    const kind = kinds.get(key);
    if (kind) kind.all.push(incident);
    else kinds.set(key, { lead: incident, all: [incident] });
  }
  return [...kinds.values()];
}

// Below this search grade the report says there is no close match (composer.py), so the panel
// says so too.
const CLOSE_MATCH = 0.35;

/** What to say before the matches when they are weak: from other systems, or not close. */
export function matchCaveat(
  incidents: Pick<SimilarIncident, "system">[],
  system: string,
  grade: number | undefined,
): string | null {
  if (incidents.length === 0) return null;
  if (incidents.every((incident) => incident.system !== system)) {
    return "Nothing like this has been seen on this system. These are the nearest incidents from other systems: read them as clues, not as fixes to follow.";
  }
  if (grade !== undefined && grade < CLOSE_MATCH) {
    return "None of these is a close match: check one before following its fix.";
  }
  return null;
}

function Incident({ kind, sameFix, system }: { kind: PastKind; sameFix: boolean; system: string }) {
  const { lead, all } = kind;
  const ids = all.flatMap((incident) => (incident.evidence_id ? [incident.evidence_id] : []));
  const sources = [...new Set(all.map((incident) => SOURCE[incident.source]).filter(Boolean))];
  return (
    <li className="grid gap-1">
      <p className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={isSeverity(lead.severity) ? lead.severity : null} size="sm" />
        <span className="font-medium">{lead.title}</span>
      </p>
      <p className="text-sm text-muted-foreground">
        {/* The same fix, card after card, says nothing new: write it once. */}
        {sameFix ? (
          "Fixed the same way as the one above."
        ) : (
          <>
            Fixed by: <CodeText>{plainResolution(lead.resolution)}</CodeText>
          </>
        )}
      </p>
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-faint">
        <span>
          Seen {lead.occurrences} {lead.occurrences === 1 ? "time" : "times"}
          {lead.mttr_minutes != null
            ? `, resolved in about ${Math.round(lead.mttr_minutes)} min`
            : ""}
          {sources.length ? `, ${sources.join(" and ")}` : ""}
          {lead.system !== system ? `, on ${systemName(lead.system)}` : ""}.
        </span>
        {/* The row stands for every sighting of this kind, and its citations are those
            sightings, each with its own details: not sources for the title above (M4). */}
        {ids.length ? (
          <span className="inline-flex flex-wrap items-center gap-1.5">
            {ids.length === 1 ? "The closest sighting:" : "The closest sightings:"}
            <Citations ids={ids} />
          </span>
        ) : null}
      </p>
    </li>
  );
}

export function SeenBefore({
  incidents,
  retrieval,
  system,
}: {
  /** The ones the report cites, else the ones retrieval found. */
  incidents: SimilarIncident[];
  retrieval: RetrievalResult | undefined;
  /** The incident's own system, to tell its matches from other systems' (J-M2). */
  system: string;
}) {
  const runbooks = retrieval?.runbooks ?? [];
  const kinds = pastKinds(incidents);
  const caveat = matchCaveat(incidents, system, retrieval?.grade);
  return (
    <section aria-labelledby="seen-title" className="grid gap-4 rounded-lg bg-raised p-5">
      <div className="grid gap-1">
        <h2 id="seen-title" className="text-xl">
          Seen before
        </h2>
        <p className="max-w-prose text-sm text-muted-foreground">
          Past incidents in ARIA&apos;s library that look like this one, and what fixed them. A
          close match suggests the same fix may work here too.
        </p>
      </div>
      {caveat ? <p className="text-sm text-muted-foreground">{caveat}</p> : null}
      {incidents.length ? (
        <ul className="grid gap-4">
          {kinds.map((kind, i) => (
            <Incident
              key={kind.lead.incident_id}
              kind={kind}
              sameFix={i > 0 && kinds[i - 1]?.lead.resolution === kind.lead.resolution}
              system={system}
            />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">
          {retrieval
            ? "Nothing like this is in the incident library yet."
            : "ARIA looks for similar past incidents after it rates the severity."}
        </p>
      )}
      {runbooks.length ? (
        <p className="text-sm">
          {runbooks.length === 1 ? "Runbook: " : "Runbooks: "}
          {runbooks.map((rb, i) => (
            <span key={rb.slug}>
              {i ? ", " : ""}
              <Link
                href={`/console/runbooks/${encodeURIComponent(rb.slug)}` as never}
                className="underline decoration-control underline-offset-2 hover:decoration-foreground"
              >
                {rb.title}
              </Link>
            </span>
          ))}
        </p>
      ) : null}
      {retrieval?.attempts.length ? (
        <details className="text-sm">
          <summary className="w-fit cursor-pointer py-0.5 text-muted-foreground hover:text-heading">
            How ARIA searched
          </summary>
          <div className="grid gap-3 pt-3">
            {retrieval.incidents.length ? (
              <ul className="grid gap-1 text-xs text-muted-foreground">
                {retrieval.incidents.map((incident) => (
                  <li key={incident.incident_id} className="flex flex-wrap gap-x-3">
                    <span className="text-foreground">{incident.title}</span>
                    <span className="tabular">words {incident.lexical_score.toFixed(2)}</span>
                    <span className="tabular">meaning {incident.dense_score.toFixed(2)}</span>
                    {incident.rerank_score != null ? (
                      <span className="tabular">rerank {incident.rerank_score.toFixed(2)}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : null}
            <ol className="grid gap-1.5 text-xs">
              {retrieval.attempts.map((a) => (
                <li key={a.attempt} className="grid gap-0.5 rounded-sm bg-sunken p-2">
                  <span className="text-muted-foreground">
                    Search {a.attempt}
                    {a.widened ? ", widened" : ""}: {a.candidates} candidates, grade{" "}
                    {a.grade.toFixed(2)}
                  </span>
                  <span className="font-mono break-words">{a.query}</span>
                </li>
              ))}
            </ol>
          </div>
        </details>
      ) : null}
    </section>
  );
}
