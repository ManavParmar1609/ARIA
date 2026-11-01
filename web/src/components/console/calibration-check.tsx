"use client";

import { useState } from "react";

import { ErrorState, LoadingRows } from "@/components/console/states";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useBlindCheck,
  useDrift,
  useRateBlind,
  type BlindCheckView,
  type BlindReveal,
} from "@/lib/api/hooks";
import { SEVERITIES, type Severity } from "@/lib/api/types";
import { count } from "@/lib/format";
import { LEVEL_WORD, orList } from "@/lib/levels";
import { cn } from "@/lib/utils";

type Case = NonNullable<BlindCheckView["case"]>;

/**
 * A blind check: one recent incident, picked at random by the server, shown as what its logs held
 * and nothing ARIA decided. The person rates it, then sees ARIA's level and short list. Ratings
 * given before seeing ARIA's answer are what recalibrate it (ADR 0014).
 */
export function BlindCheck() {
  const [started, setStarted] = useState(false);
  const check = useBlindCheck(started);
  const rate = useRateBlind();
  const [reveal, setReveal] = useState<BlindReveal | null>(null);

  const next = async () => {
    setReveal(null);
    rate.reset();
    if (started) await check.refetch();
    else setStarted(true);
  };

  if (!started) {
    return (
      <div className="grid justify-items-start gap-3">
        <Button onClick={next}>Rate an incident blind</Button>
      </div>
    );
  }
  if (check.isPending || check.isFetching) {
    return <LoadingRows rows={3} label="Picking an incident" />;
  }
  if (check.isError) {
    return (
      <ErrorState
        title="No incident could be picked"
        error={check.error}
        onRetry={() => void check.refetch()}
      />
    );
  }
  const data = check.data;
  if (!data.case) {
    return (
      <p className="text-sm text-muted-foreground">
        Nothing left to rate: every recent incident has been rated blind.{" "}
        {data.checks > 0 ? `${count(data.checks)} blind checks so far.` : null}
      </p>
    );
  }
  const item = data.case;
  return (
    <div className="grid gap-4">
      <CaseView item={item} />
      {reveal ? (
        <Reveal reveal={reveal} onNext={next} />
      ) : (
        <fieldset className="grid gap-2" disabled={rate.isPending}>
          <legend className="pb-1 font-medium">How serious is it?</legend>
          <div className="flex flex-wrap gap-2">
            {SEVERITIES.map((level) => (
              <Button
                key={level}
                variant="raised"
                onClick={async () =>
                  setReveal(await rate.mutateAsync({ runId: item.run_id, severity: level }))
                }
              >
                {level} · {LEVEL_WORD[level]}
              </Button>
            ))}
          </div>
          {rate.isError ? (
            <p role="alert" className="text-sm text-sev1-fg">
              Your rating was not saved. Try again.
            </p>
          ) : null}
        </fieldset>
      )}
      {!data.counted ? (
        <p className="text-xs text-muted-foreground">
          On this shared demo your ratings are not used to recalibrate ARIA, so no visitor can skew
          it.
        </p>
      ) : null}
    </div>
  );
}

function CaseView({ item }: { item: Case }) {
  const facts = [
    `${count(item.lines)} lines`,
    `${count(item.error_lines)} errors`,
    `${count(item.warning_lines)} warnings`,
    `${count(item.nodes)} ${item.nodes === 1 ? "machine" : "machines"}`,
    `${item.minutes} min`,
  ];
  return (
    <div className="grid gap-3">
      <p className="text-sm">
        <span className="font-medium">{item.system}</span>
        <span className="text-muted-foreground"> · {facts.join(" · ")}</span>
      </p>
      <ul className="grid gap-1.5" aria-label="The incident's log patterns">
        {item.patterns.map((p, i) => (
          <li
            key={`${i}-${p.template}`}
            className={cn(
              "grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-3 border-l-2 pl-3",
              p.error_like ? "border-sev2-fg/60" : "border-rule",
            )}
          >
            <span className="tabular text-xs text-muted-foreground">{count(p.count)}×</span>
            <span className="font-mono text-xs break-words">
              {p.template}
              {p.error_like ? <span className="sr-only"> (looks like an error)</span> : null}
              {p.new ? (
                <span className="ml-2 rounded-xs border border-control px-1 font-sans text-xs text-muted-foreground">
                  new
                </span>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Reveal({ reveal, onNext }: { reveal: BlindReveal; onNext: () => void }) {
  const said = (level: Severity) => `${level} (${LEVEL_WORD[level]})`;
  return (
    <div className="grid gap-3" aria-live="polite">
      <p className="text-sm">
        You said {said(reveal.yours)}. ARIA said {said(reveal.aria)}, with a short list of{" "}
        {orList(reveal.prediction_set)}.{" "}
        <span className="font-medium">
          {reveal.agreed
            ? "You agree."
            : reveal.held
              ? "Your level was on its short list."
              : "Your level was not on its short list: that is the miss recalibration corrects."}
        </span>
      </p>
      {reveal.counted ? (
        <p className="text-xs text-muted-foreground">
          {count(reveal.checks)} blind {reveal.checks === 1 ? "check" : "checks"} so far. ARIA
          adjusts its short lists after each one.
        </p>
      ) : null}
      <div>
        <Button variant="raised" onClick={onNext}>
          Rate another
        </Button>
      </div>
    </div>
  );
}

/** Per system: did the levels ARIA decided lately shift from the ones it decided before? */
export function DriftReport() {
  const drift = useDrift();
  if (drift.isPending) return <LoadingRows rows={3} label="Comparing recent runs" />;
  if (drift.isError) {
    return (
      <ErrorState
        title="The comparison could not be loaded"
        error={drift.error}
        onRetry={() => void drift.refetch()}
      />
    );
  }
  const { systems, too_few_runs: few, min_runs: least } = drift.data;
  return (
    <div className="grid gap-3">
      {systems.length ? (
        <Table aria-label="Severity mix, earlier runs against recent runs, by system">
          <TableHeader>
            <TableRow>
              <TableHead>System</TableHead>
              <TableHead>Runs compared</TableHead>
              <TableHead>Earlier</TableHead>
              <TableHead>Recent</TableHead>
              <TableHead>Verdict</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {systems.map((s) => (
              <TableRow key={s.system}>
                <TableCell>{s.system}</TableCell>
                <TableCell className="tabular">{count(s.compared)} each</TableCell>
                <TableCell className="tabular text-xs">{mix(s.reference)}</TableCell>
                <TableCell className="tabular text-xs">{mix(s.recent)}</TableCell>
                <TableCell>
                  {s.shifted ? (
                    <span className="font-medium">Shifted beyond chance</span>
                  ) : (
                    <span className="text-muted-foreground">Steady</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : (
        <p className="text-sm text-muted-foreground">
          Not enough runs yet: a system needs {least} decided runs before ARIA compares its earlier
          and recent levels.
        </p>
      )}
      {few.length ? (
        <p className="text-xs text-muted-foreground">
          Too few runs to compare yet: {orList(few).replace(" or ", " and ")}.
        </p>
      ) : null}
    </div>
  );
}

function mix(counts: Record<string, number>): string {
  return SEVERITIES.map((level) => `${level} ${counts[level] ?? 0}`).join(", ");
}
