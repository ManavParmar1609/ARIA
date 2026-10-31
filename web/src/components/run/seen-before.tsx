"use client";

import Link from "next/link";

import { SeverityBadge } from "@/components/aria/severity";
import { CodeText } from "@/components/ui/code-text";
import type { RetrievalResult, SimilarIncident } from "@/lib/api/types";
import { isSeverity } from "@/lib/api/types";
import { plainResolution } from "@/lib/format";

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

function Incident({ incident, sameFix }: { incident: SimilarIncident; sameFix: boolean }) {
  return (
    <li className="grid gap-1">
      <p className="flex flex-wrap items-center gap-2">
        <SeverityBadge
          severity={isSeverity(incident.severity) ? incident.severity : null}
          size="sm"
        />
        <span className="font-medium">{incident.title}</span>
        {incident.evidence_id ? <Citations ids={[incident.evidence_id]} /> : null}
      </p>
      <p className="text-sm text-muted-foreground">
        {/* The same fix, card after card, says nothing new: write it once. */}
        {sameFix ? (
          "Fixed the same way as the one above."
        ) : (
          <>
            Fixed by: <CodeText>{plainResolution(incident.resolution)}</CodeText>
          </>
        )}
      </p>
      <p className="text-xs text-faint">
        seen {incident.occurrences} {incident.occurrences === 1 ? "time" : "times"}
        {incident.mttr_minutes != null
          ? `, resolved in about ${Math.round(incident.mttr_minutes)} min`
          : ""}
        {SOURCE[incident.source] ? `, ${SOURCE[incident.source]}` : ""}
      </p>
    </li>
  );
}

export function SeenBefore({
  incidents,
  retrieval,
}: {
  /** The ones the report cites, else the ones retrieval found. */
  incidents: SimilarIncident[];
  retrieval: RetrievalResult | undefined;
}) {
  const runbooks = retrieval?.runbooks ?? [];
  return (
    <section aria-labelledby="seen-title" className="grid gap-4 rounded-lg bg-raised p-5">
      <h2 id="seen-title" className="text-base font-medium">
        Seen before
      </h2>
      {incidents.length ? (
        <ul className="grid gap-4">
          {incidents.map((incident, i, all) => (
            <Incident
              key={incident.incident_id}
              incident={incident}
              sameFix={i > 0 && all[i - 1]?.resolution === incident.resolution}
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
          <summary className="w-fit cursor-pointer text-muted-foreground hover:text-heading">
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
