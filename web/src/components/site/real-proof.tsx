import Link from "next/link";

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
      <dd className="stat order-1 text-[2.75rem] sm:text-5xl xl:text-[5.375rem]">{value}</dd>
    </div>
  );
}

/** Precision and recall for each way of finding failed blocks, on a 0-100% scale. */
function Comparison({ data }: { data: RealLogs }) {
  const rows = [
    { key: "aria", label: "ARIA, following each block's steps", ...data.lifecycle },
    { key: "engine", label: "ARIA's severity engine, one block at a time", ...data.engine },
    { key: "keyword", label: "A keyword rule, one block at a time", ...data.keyword },
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
        <span className="text-lg tracking-heading">Three ways to find the failed blocks</span>
        <span className="text-sm text-muted-foreground">
          Precision: of the blocks flagged, the share that failed. Recall: of the failed blocks
          judged, the share flagged.
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
  const allVisible = data.visible.caught === data.visible.anomalous;
  return (
    <div className="grid gap-16 lg:gap-20">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-12 lg:grid-cols-4">
        <Headline
          value={pct(data.lifecycle.precision)}
          label="Flags that were real failures"
          note={`${n(data.lifecycle.falseAlarms)} false alarms among ${n(data.lifecycle.healthy)} healthy blocks`}
        />
        <Headline
          value={pct(data.visible.recall, allVisible ? 0 : 1)}
          label="Visible failures caught"
          note={`${n(data.visible.caught)} of the ${n(data.visible.anomalous)} failed blocks whose log differs from a healthy one`}
        />
        <Headline
          value={pct(data.lifecycle.recall)}
          label="Of all labelled failures"
          note={`the other ${n(data.visible.lookHealthy)} take exactly a healthy block's steps in this stretch of log`}
        />
        <Headline
          value={pct(data.keyword.precision)}
          label="A keyword rule's flags that were real"
          note={`it flags ${pct(data.keyword.falseAlarmRate, 0)} of healthy blocks too, which is why ARIA follows each block instead`}
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
            blocks whose steps don&rsquo;t add up. It needs no labels and no training, so it works
            on a system it has never seen.
          </p>
          {data.topPattern ? (
            <p className="text-muted-foreground">
              The commonest break in this log: {data.topPattern.pattern}, in{" "}
              {n(data.topPattern.blocks)} blocks.
            </p>
          ) : null}
          <p className="text-sm text-faint">
            Replayed as ARIA&rsquo;s log scan would: {data.windows} overlapping {data.windowMin}
            -minute windows, {n(data.judged)} blocks judged. Labels: {data.citation}
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
