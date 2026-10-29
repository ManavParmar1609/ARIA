import Link from "next/link";

import { RollingNumber } from "@/components/aria/rolling-number";
import { ArrowCircle, Button } from "@/components/ui/button";
import { EVAL_DOC_URL, type RealLogs } from "@/lib/site-data";
import { cn } from "@/lib/utils";

const pct = (x: number, digits = 1) => `${(x * 100).toFixed(digits)}%`;
const n = (x: number) => x.toLocaleString("en");

/** A headline number: large, in ink, with its name and what it counts. */
function Headline({ value, label, note }: { value: string; label: string; note: string }) {
  return (
    <div className="grid content-start gap-4">
      <dt className="order-2 grid gap-1.5">
        <span className="eyebrow text-foreground">{label}</span>
        <span className="text-sm text-muted-foreground">{note}</span>
      </dt>
      <dd className="stat order-1 text-[2.75rem] sm:text-5xl xl:text-[5.375rem]">
        <RollingNumber value={value} />
      </dd>
    </div>
  );
}

/** Precision and recall for each way of finding failed blocks, on a 0-100% scale. */
function Comparison({ data }: { data: RealLogs }) {
  const rows = [
    { key: "aria", label: "ARIA, following each block's steps", ...data.lifecycle },
    ...data.detectors,
  ];
  const bar = (value: number, strong: boolean) => (
    <span aria-hidden className="relative block h-2.5 rounded-xs bg-sunken">
      <span
        className={cn("block h-2.5 rounded-xs", strong ? "bg-grass-deep" : "bg-control")}
        style={{ width: `${Math.max(0.5, value * 100)}%` }}
      />
    </span>
  );
  return (
    <figure className="grid gap-4 rounded-lg bg-raised p-5 sm:p-8">
      <figcaption className="grid gap-1">
        <span className="text-lg tracking-heading">ARIA beside standard detectors</span>
        <span className="text-sm text-muted-foreground">
          On the same {n(data.judged)} blocks. Precision: of the blocks flagged, the share that
          failed. Recall: of the failed blocks, the share flagged. The four standard detectors see
          the whole sample at once; ARIA sees one window at a time.
        </span>
      </figcaption>
      <ul className="grid gap-6">
        {rows.map((row) => {
          const strong = row.key === "aria";
          return (
            <li key={row.key} className="grid gap-2">
              <span
                className={cn(
                  "text-sm leading-tight",
                  strong ? "font-medium text-foreground" : "text-muted-foreground",
                )}
              >
                {row.label}
              </span>
              <dl className="grid grid-cols-[4.75rem_minmax(0,1fr)_3.5rem] items-center gap-x-3 gap-y-1.5 text-sm">
                <dt className="text-faint">Precision</dt>
                <dd>{bar(row.precision, strong)}</dd>
                <dd className="tabular text-right">{pct(row.precision)}</dd>
                <dt className="text-faint">Recall</dt>
                <dd>{bar(row.recall, strong)}</dd>
                <dd className="tabular text-right">{pct(row.recall)}</dd>
              </dl>
            </li>
          );
        })}
      </ul>
    </figure>
  );
}

/** The landing page's proof on real logs, every number from the committed evaluation. */
export function RealProof({ data }: { data: RealLogs }) {
  const matched = data.detectors.filter((d) => data.lifecycle.f1 >= d.f1).length;
  return (
    <div className="grid gap-16 lg:gap-20">
      <dl className="grid gap-x-6 gap-y-12 sm:grid-cols-3">
        <Headline
          value={pct(data.lifecycle.precision)}
          label="Flags that were real failures"
          note={`${n(data.lifecycle.falseAlarms)} false alarms among ${n(data.lifecycle.healthy)} healthy blocks`}
        />
        <Headline
          value={pct(data.lifecycle.recall)}
          label="Failures caught, of those judged"
          note={`${n(data.lifecycle.flagged - data.lifecycle.falseAlarms)} of ${n(data.judgedFailed)}; ${pct(data.recallAll)} of all ${n(data.failedBlocks)}, counting blocks no window saw whole`}
        />
        <Headline
          value={`${matched} of ${data.detectors.length}`}
          label="Standard detectors matched or beaten"
          note="PCA, an isolation forest and count pairs; a rule that flags rare step counts ties it"
        />
      </dl>

      <div className="grid gap-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16">
        <div className="grid content-start gap-5">
          <h3 className="text-2xl leading-tight tracking-heading sm:text-3xl">
            How ARIA catches a failure nobody logged
          </h3>
          <p className="text-muted-foreground">
            A block written to three datanodes should be received three times and confirmed three
            times. ARIA learns from each window which steps come in equal numbers, then flags the
            blocks whose steps don&rsquo;t add up. It needs no labels and no training. The failures
            it misses take exactly the steps of a common healthy block.
          </p>
          {data.topPattern ? (
            <p className="text-muted-foreground">
              The commonest break in this log: {data.topPattern.pattern}, in{" "}
              {n(data.topPattern.blocks)} blocks.
            </p>
          ) : null}
          <p className="text-sm text-faint">
            An offline replay of the check: {data.windows} overlapping {data.windowMin}-minute
            windows, {n(data.judged)} of {n(data.blocks)} blocks judged.
            {data.head
              ? ` The sample is the log's first ${n(data.head.lines)} lines plus later lines of the same blocks; on those ${n(data.head.lines)} lines alone, ARIA flags ${n(data.head.flagged)} blocks with ${n(data.head.falseAlarms)} false alarms.`
              : ""}{" "}
            Measured on this one log; other systems are untested. Labels: {data.citation}
          </p>
          <div className="flex flex-wrap gap-3">
            <Button asChild variant="raised" size="md" className="pr-1.5">
              <Link href="/console/guide">
                Replay it yourself
                <ArrowCircle tone="grass" size="md" />
              </Link>
            </Button>
            <Button asChild variant="ghost" size="md">
              <a href={`${EVAL_DOC_URL}#real-logs-expert-labels`}>How it was measured</a>
            </Button>
          </div>
        </div>
        <Comparison data={data} />
      </div>
    </div>
  );
}
