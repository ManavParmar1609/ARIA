"use client";

import { ErrorState, LoadingRows } from "@/components/console/states";
import { useExpertCheck, type ExpertCheck as Check } from "@/lib/api/hooks";

import { Citations } from "./evidence";

const plural = (n: number, word: string) =>
  `${n.toLocaleString("en")} ${word}${n === 1 ? "" : "s"}`;

// Words, not colours: a pop never marks a state (DESIGN.md), and the label is the state.
function Verdict({ failed }: { failed: boolean | null | undefined }) {
  if (failed == null) return <span className="text-faint">Not labelled</span>;
  return failed ? (
    <span className="font-medium">Failed</span>
  ) : (
    <span className="text-muted-foreground">Healthy</span>
  );
}

function Lead({ check }: { check: Check }) {
  const flagged = check.flagged.length;
  if (!flagged) {
    return (
      <p className="text-lead">
        ARIA flagged no {check.unit}s in this replay. The experts labelled{" "}
        {plural(check.labelled_failures, check.unit)} in it as failed.
      </p>
    );
  }
  return (
    <p className="text-lead">
      ARIA flagged {plural(flagged, check.unit)}.{" "}
      {check.flagged_failed === flagged
        ? "The experts labelled every one of them as failed."
        : `The experts labelled ${check.flagged_failed.toLocaleString("en")} of them as failed.`}
    </p>
  );
}

/**
 * For a replayed real incident: what ARIA flagged, next to the labels the system's experts gave.
 * ARIA never saw these labels; they come with the dataset, so anyone can check its work.
 */
export function ExpertCheck({ runId }: { runId: string }) {
  const check = useExpertCheck(runId, true);
  return (
    <section
      aria-labelledby="expert-check-title"
      className="grid gap-4 rounded-lg bg-raised p-5 sm:p-6"
    >
      <div className="grid gap-1">
        <p className="eyebrow flex items-center gap-2 text-muted-foreground">
          <span aria-hidden className="size-2 rounded-full bg-grass" />
          Real logs, real labels
        </p>
        <h2 id="expert-check-title" className="text-xl tracking-heading">
          Check ARIA against the experts
        </h2>
      </div>
      {check.isPending ? (
        <LoadingRows rows={2} label="Loading the experts' labels" />
      ) : check.isError ? (
        <ErrorState
          error={check.error}
          title="The labels could not be loaded"
          onRetry={() => void check.refetch()}
        />
      ) : !check.data.ready ? (
        <p role="status" className="text-muted-foreground">
          Waiting for ARIA to read the logs. The comparison appears once it has.
        </p>
      ) : (
        <>
          <Lead check={check.data} />
          <p className="text-sm text-muted-foreground">
            ARIA never saw these labels. The experts labelled{" "}
            {plural(check.data.labelled_failures, check.data.unit)} of the{" "}
            {check.data.units.toLocaleString("en")} in this log as failed, judging from the
            cluster&rsquo;s whole log: some of those look healthy in this stretch, and ARIA only
            judges a {check.data.unit} it saw from start to finish.
          </p>
          {check.data.flagged.length ? (
            <div className="overflow-x-auto rounded-md bg-sunken">
              <table className="w-full min-w-[34rem] text-left text-sm">
                <caption className="sr-only">
                  Each {check.data.unit} ARIA flagged, why, and the experts&rsquo; label
                </caption>
                <thead className="text-xs text-muted-foreground">
                  <tr>
                    <th scope="col" className="px-4 py-2.5 font-medium">
                      {check.data.unit.charAt(0).toUpperCase() + check.data.unit.slice(1)}
                    </th>
                    <th scope="col" className="px-4 py-2.5 font-medium">
                      Why ARIA flagged it
                    </th>
                    <th scope="col" className="px-4 py-2.5 font-medium">
                      The experts&rsquo; label
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {check.data.flagged.map((unit) => (
                    <tr key={unit.key} className="border-t border-rule align-baseline">
                      <td className="px-4 py-2.5 font-mono text-xs">{unit.key}</td>
                      <td className="px-4 py-2.5">
                        {unit.reason ?? (
                          <span className="text-faint">Listed in the run&rsquo;s evidence</span>
                        )}{" "}
                        {unit.evidence_id ? <Citations ids={[unit.evidence_id]} /> : null}
                      </td>
                      <td className="px-4 py-2.5 whitespace-nowrap">
                        <Verdict failed={unit.failed} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          <p className="text-xs text-faint">Labels: {check.data.citation}</p>
        </>
      )}
    </section>
  );
}
