import { RollingNumber } from "@/components/aria/rolling-number";
import { PageHeader } from "@/components/console/states";
import { BaselineChart, RiskCoverageChart } from "@/components/site/charts";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { SEVERITIES } from "@/lib/api/types";
import { EVAL_DOC_URL, type Evaluation, type RealLogs } from "@/lib/site-data";
import { systemName } from "@/lib/systems";
import { cn } from "@/lib/utils";

const pct = (x: number | undefined, digits = 1) =>
  x == null ? "" : `${(x * 100).toFixed(digits)}%`;

function Section({
  id,
  title,
  intro,
  children,
}: {
  id: string;
  title: string;
  intro?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="grid gap-5 border-t border-rule pt-8">
      <div className="grid max-w-3xl gap-2">
        <h2 id={id} className="text-xl tracking-heading">
          {title}
        </h2>
        {intro ? <p className="text-muted-foreground">{intro}</p> : null}
      </div>
      {children}
    </section>
  );
}

function Facts({ items }: { items: [string, string][] }) {
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-6 sm:grid-cols-3 xl:grid-cols-6">
      {items.map(([label, value]) => (
        <div key={label} className="grid content-start gap-2 border-t border-rule pt-3">
          <dt className="order-2 text-sm text-muted-foreground">{label}</dt>
          <dd className="stat order-1 text-[1.75rem]">
            <RollingNumber value={value} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Horizontal bars with the value written at the end; real text, no script. */
function Bars({
  rows,
  max = 1,
  format = (v: number) => pct(v),
  label,
}: {
  rows: [string, number][];
  max?: number;
  format?: (v: number) => string;
  label: string;
}) {
  return (
    <ul aria-label={label} className="grid gap-1.5">
      {rows.map(([name, value]) => (
        <li
          key={name}
          className="grid grid-cols-[minmax(0,7rem)_1fr_3.5rem] items-center gap-3 text-sm sm:grid-cols-[minmax(7rem,11rem)_1fr_4rem]"
        >
          <span className="truncate text-muted-foreground">{name}</span>
          <span className="h-2.5 rounded-xs bg-sunken" aria-hidden>
            <span
              className="block h-2.5 rounded-xs bg-primary/80"
              style={{ width: `${Math.min(100, (value / max) * 100)}%` }}
            />
          </span>
          <span className="tabular text-right">{format(value)}</span>
        </li>
      ))}
    </ul>
  );
}

function Confusion({ matrix }: { matrix: number[][] }) {
  return (
    <figure className="grid gap-2">
      <Table aria-label="Confusion matrix: rows are the true severity, columns what ARIA decided">
        <TableHeader>
          <TableRow>
            <TableHead className="w-24">True \ ARIA</TableHead>
            {SEVERITIES.map((s) => (
              <TableHead key={s} className="text-center">
                {s}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {matrix.map((row, i) => {
            const total = row.reduce((a, b) => a + b, 0) || 1;
            return (
              <TableRow key={SEVERITIES[i]}>
                <TableHead scope="row">{SEVERITIES[i]}</TableHead>
                {row.map((n, j) => {
                  const share = n / total;
                  const under = j > i; // rated less severe than it was
                  // tints stay light enough for text to keep 4.5:1 in both themes
                  return (
                    <TableCell
                      key={j}
                      className={cn(
                        "tabular text-center",
                        i === j && "font-medium",
                        under && n > 0 && "text-danger",
                      )}
                      style={{
                        backgroundColor:
                          n > 0
                            ? `color-mix(in oklch, var(${i === j ? "--primary" : under ? "--danger" : "--control"}) ${Math.round(6 + share * 18)}%, transparent)`
                            : undefined,
                      }}
                    >
                      {n}
                    </TableCell>
                  );
                })}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      <figcaption className="text-xs text-muted-foreground">
        Rows: the labelled severity. Columns: ARIA&apos;s decision. Red cells were rated less severe
        than they were.
      </figcaption>
    </figure>
  );
}

function RealSection({ real }: { real: RealLogs }) {
  const methods = [
    ["ARIA, following each block's steps", real.lifecycle],
    ...real.detectors.map((d) => [d.label, d] as const),
    ["ARIA's severity engine, one block at a time", real.engine],
    ["Keyword rule, one block at a time", real.keyword],
  ] as const;
  return (
    <Section
      id="ev-real"
      title="Real logs, expert labels"
      intro={
        <>
          {real.lines.toLocaleString("en")} real lines from a Hadoop cluster, replayed offline in{" "}
          {real.windows} overlapping {real.windowMin}-minute windows, against the label Hadoop
          experts gave each storage block. ARIA judged {real.judged.toLocaleString("en")} of the{" "}
          {real.blocks.toLocaleString("en")} blocks, {real.judgedFailed} of them failed. It never
          sees a label.
          {real.fixture
            ? " These numbers come from the small committed cut, not the full sample."
            : ""}
        </>
      }
    >
      <Facts
        items={[
          ["Precision", pct(real.lifecycle.precision)],
          ["Recall, judged blocks", pct(real.lifecycle.recall)],
          ["Recall, all failures", pct(real.recallAll)],
          ["F1", real.lifecycle.f1.toFixed(3)],
          [
            "False alarms",
            `${real.lifecycle.falseAlarms} of ${real.lifecycle.healthy.toLocaleString("en")}`,
          ],
          ["Blocks judged", pct(real.coverage)],
        ]}
      />
      <Table aria-label="Finding failed blocks: ARIA against standard detectors">
        <TableHeader>
          <TableRow>
            <TableHead>Method, per judged block</TableHead>
            <TableHead className="text-right">Precision</TableHead>
            <TableHead className="text-right">Recall</TableHead>
            <TableHead className="text-right">F1</TableHead>
            <TableHead className="text-right">False alarms</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {methods.map(([name, m]) => (
            <TableRow key={name}>
              <TableHead scope="row">{name}</TableHead>
              <TableCell className="tabular text-right">{pct(m.precision)}</TableCell>
              <TableCell className="tabular text-right">{pct(m.recall)}</TableCell>
              <TableCell className="tabular text-right">{m.f1.toFixed(3)}</TableCell>
              <TableCell className="tabular text-right">
                {m.falseAlarms.toLocaleString("en")}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="max-w-3xl text-sm text-muted-foreground">
        The standard detectors read the experts&rsquo; event templates and fit on the whole sample
        at once; ARIA parses each window itself. ARIA flagged all {real.steps.distinctCaught}{" "}
        failures whose step counts no healthy block shares, and {real.steps.lookAlikeCaught} of the{" "}
        {real.steps.lookAlike} whose counts some healthy blocks share. Each of the{" "}
        {real.steps.missed} it missed takes exactly the steps of one of {real.steps.missedPatterns}{" "}
        common healthy patterns, shared by at least {real.steps.missedTwinsMin.toLocaleString("en")}{" "}
        healthy blocks.
        {real.head
          ? ` The sample is the log's first ${real.head.lines.toLocaleString("en")} lines plus later lines of the same blocks; on those lines alone ARIA flags ${real.head.flagged} blocks, ${pct(real.head.precision)} of them real failures (${pct(real.head.recallAll)} of all failures).`
          : ""}{" "}
        The deployed log scan opens a run on a burst of errors, and this log has none.
      </p>
      <p className="max-w-3xl text-sm text-muted-foreground">
        A block is judged only in a window that holds its whole life, so the window length moves the
        result most (ARIA uses {real.windowMin} minutes):
      </p>
      <Table aria-label="How the real-log result depends on the window length">
        <TableHeader>
          <TableRow>
            <TableHead>Window</TableHead>
            <TableHead className="text-right">Judged</TableHead>
            <TableHead className="text-right">Precision</TableHead>
            <TableHead className="text-right">Recall, judged</TableHead>
            <TableHead className="text-right">Recall, all failures</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {real.windowLengths.map((row) => (
            <TableRow
              key={row.window_min}
              className={cn(row.window_min === real.windowMin && "bg-highlight/40")}
            >
              <TableCell className="tabular">{row.window_min} min</TableCell>
              <TableCell className="tabular text-right">
                {row.judged.toLocaleString("en")}
              </TableCell>
              <TableCell className="tabular text-right">{pct(row.precision)}</TableCell>
              <TableCell className="tabular text-right">{pct(row.recall)}</TableCell>
              <TableCell className="tabular text-right">{pct(row.recall_all)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="max-w-3xl text-sm text-muted-foreground">
        And with the two settings of the check (ARIA uses {real.minSupport} and{" "}
        {real.settleQuantile}, chosen on this log with its labels in view):
      </p>
      <Table aria-label="How the real-log result depends on ARIA's two settings">
        <TableHeader>
          <TableRow>
            <TableHead>Pair support</TableHead>
            <TableHead>Settle quantile</TableHead>
            <TableHead className="text-right">Judged</TableHead>
            <TableHead className="text-right">Precision</TableHead>
            <TableHead className="text-right">Recall</TableHead>
            <TableHead className="text-right">False alarms</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {real.sensitivity.map((row) => (
            <TableRow
              key={`${row.min_support}-${row.settle_quantile}`}
              className={cn(
                row.min_support === real.minSupport &&
                  row.settle_quantile === real.settleQuantile &&
                  "bg-highlight/40",
              )}
            >
              <TableCell className="tabular">{row.min_support}</TableCell>
              <TableCell className="tabular">{row.settle_quantile}</TableCell>
              <TableCell className="tabular text-right">
                {row.judged.toLocaleString("en")}
              </TableCell>
              <TableCell className="tabular text-right">{pct(row.precision)}</TableCell>
              <TableCell className="tabular text-right">{pct(row.recall)}</TableCell>
              <TableCell className="tabular text-right">{row.fp}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Section>
  );
}

export function Evals({ data, real }: { data: Evaluation; real?: RealLogs }) {
  const s = data.severity;
  const p = data.pipeline;
  const r = data.robustness;
  const live = data.live;
  const stages = Object.entries(p.stageP50).sort((a, b) => b[1] - a[1]);
  return (
    <div className="grid gap-10">
      <PageHeader
        title="Evaluation"
        description={
          <>
            Severity, end-to-end and robustness results are measured on {data.dataDescription}; the
            real-log section on a real HDFS log with expert labels. Results from commit{" "}
            <code>{data.gitSha}</code>, run {data.createdAt.slice(0, 10)}; <code>make eval</code>{" "}
            reproduces them, and CI&rsquo;s smoke gate fails on a regression in severity, parsing,
            retrieval or reporting.{" "}
            <a
              href={EVAL_DOC_URL}
              className="text-foreground underline decoration-control underline-offset-4"
            >
              Read the full write-up
            </a>
            .
          </>
        }
      />

      {real ? <RealSection real={real} /> : null}

      <Section
        id="ev-severity"
        title="Severity"
        intro={`${s.n} labelled windows. ARIA's policy against simpler methods on the same windows.`}
      >
        <Facts
          items={[
            ["Accuracy", pct(s.accuracy)],
            ["95% interval", `${pct(s.ci[0] ?? 0)} to ${pct(s.ci[1] ?? 0)}`],
            ["Macro-F1", s.macroF1.toFixed(3)],
            ["Weighted kappa", s.kappa.toFixed(3)],
            ["SEV1 or SEV2 rated SEV3 or SEV4", pct(s.severeUnderTriage)],
            ["Rated too high", pct(s.overTriage)],
          ]}
        />
        <div className="grid gap-8 xl:grid-cols-2">
          <BaselineChart methods={s.methods} />
          <Confusion matrix={s.confusion} />
        </div>
        <Table aria-label="Precision and recall by severity">
          <TableHeader>
            <TableRow>
              <TableHead>Severity</TableHead>
              <TableHead className="text-right">Precision</TableHead>
              <TableHead className="text-right">Recall</TableHead>
              <TableHead className="text-right">F1</TableHead>
              <TableHead className="text-right">Windows</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {SEVERITIES.map((sev) => {
              const c = s.perClass[sev];
              return (
                <TableRow key={sev}>
                  <TableHead scope="row">{sev}</TableHead>
                  <TableCell className="tabular text-right">{pct(c?.precision)}</TableCell>
                  <TableCell className="tabular text-right">{pct(c?.recall)}</TableCell>
                  <TableCell className="tabular text-right">{c?.f1.toFixed(3)}</TableCell>
                  <TableCell className="tabular text-right">{c?.support}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </Section>

      <Section
        id="ev-calibration"
        title="Calibration and knowing when not to decide"
        intro="A confident wrong answer is worse than a flagged one. These measure whether ARIA's confidence means what it says."
      >
        <Facts
          items={[
            ["Expected calibration error", s.ece.toFixed(3)],
            ["Brier score", s.brier.toFixed(3)],
            [`Coverage of the ${Math.round(s.targetCoverage * 100)}% sets`, pct(s.coverage)],
            ["With safety floors", pct(s.coverageWithFloors)],
            ["Mean set size", s.setSize.toFixed(3)],
            ["Area under risk-coverage", s.aurc.toFixed(3)],
          ]}
        />
        <div className="grid gap-8 xl:grid-cols-2">
          <RiskCoverageChart
            points={s.riskCoverage}
            operating={{ coverage: s.autoDecided, accuracy: s.accuracyWhenAuto }}
          />
          <div className="grid content-start gap-3 text-sm">
            <p>
              ARIA decided <strong>{pct(s.autoDecided)}</strong> of windows alone, at{" "}
              {pct(s.accuracyWhenAuto)} accuracy. Of the rest, which it sent to review, its own
              guess was right {pct(s.accuracyWhenFlagged)} of the time.
            </p>
            <Bars
              label="Who decided"
              rows={Object.entries(s.decidedBy).map(
                ([k, v]) => [k === "fallback" ? "flagged for review" : k, v] as [string, number],
              )}
              max={s.n}
              format={(v) => `${v}`}
            />
          </div>
        </div>
      </Section>

      <Section
        id="ev-systems"
        title="By system"
        intro="Labels come from the scenario policy, except BlueGene/L, which uses its real alert tags."
      >
        <Table aria-label="Severity accuracy by system">
          <TableHeader>
            <TableRow>
              <TableHead>System</TableHead>
              <TableHead className="text-right">Windows</TableHead>
              <TableHead className="text-right">Accuracy</TableHead>
              <TableHead className="text-right">Severe under-triage</TableHead>
              <TableHead>Labels from</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {Object.entries(s.bySystem).map(([system, v]) => (
              <TableRow key={system}>
                <TableHead scope="row">{systemName(system)}</TableHead>
                <TableCell className="tabular text-right">{v.n}</TableCell>
                <TableCell className="tabular text-right">{pct(v.accuracy)}</TableCell>
                <TableCell
                  className={cn("tabular text-right", v.severe_under_triage > 0 && "text-danger")}
                >
                  {pct(v.severe_under_triage)}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {v.label_source.replaceAll("_", " ")}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Section>

      <Section
        id="ev-pipeline"
        title="End to end"
        intro={`${p.n} runs through the whole graph, offline, to the review pause.`}
      >
        <Facts
          items={[
            ["Reports that validated", pct(p.valid, 0)],
            ["Every claim cited", pct(p.cited, 0)],
            ["Similar incident in top 3", pct(p.recallAt3, 0)],
            ["Leading hypothesis correct", pct(p.leadingCorrect, 0)],
            [
              "False alarms on quiet windows",
              `${Math.round(p.falseAlarms * p.quietRuns)} of ${p.quietRuns}`,
            ],
            ["Time to review, p50 / p95", `${p.p50s.toFixed(2)} / ${p.p95s.toFixed(2)} s`],
          ]}
        />
        <div className="grid gap-3">
          <h3 className="text-sm font-medium">Median time per step</h3>
          <Bars
            label="Median milliseconds per graph step"
            rows={stages}
            max={stages[0]?.[1] ?? 1}
            format={(v) => `${Math.round(v)} ms`}
          />
        </div>
      </Section>

      <Section
        id="ev-robustness"
        title="Parsing, edge cases and injection"
        intro={`Template grouping against Loghub's hand labels, and ${r.edgeN.toLocaleString("en")} hostile or broken inputs.`}
      >
        <div className="grid gap-8 xl:grid-cols-2">
          <div className="grid content-start gap-3">
            <h3 className="text-sm font-medium">
              Grouping accuracy by system (mean {data.parsing.meanAccuracy.toFixed(3)})
            </h3>
            <Bars
              label="Grouping accuracy by system"
              rows={Object.entries(data.parsing.bySystem)
                .map(([k, v]) => [systemName(k), v.grouping_accuracy] as [string, number])
                .sort((a, b) => b[1] - a[1])}
              format={(v) => v.toFixed(3)}
            />
          </div>
          <div className="grid content-start gap-3">
            <h3 className="text-sm font-medium">
              Attacks quarantined, by family (overall {pct(r.attackRecall)})
            </h3>
            <Bars
              label="Attack recall by family"
              rows={Object.entries(r.byFamily)
                .map(([k, v]) => [k.replaceAll("_", " "), v] as [string, number])
                .sort((a, b) => a[1] - b[1])}
            />
            <p className="text-sm text-muted-foreground">
              Parser errors: {r.parserErrors}. Benign lines quarantined:{" "}
              {pct(r.benignFalsePositives)}. With planted instructions in {r.windows} incident
              windows, severity stayed the same in {pct(r.severityInvariant, 0)} and tool use in{" "}
              {pct(r.toolUseInvariant, 0)}; {r.reportsWithInjectedText} reports repeated injected
              text. The detector was tuned on this corpus, so read the recall as an upper bound.
            </p>
          </div>
        </div>
      </Section>

      <Section
        id="ev-live"
        title="With a live model"
        intro={`${live.n} runs through hosted NVIDIA NIM models, ${live.createdAt.slice(0, 10)}.`}
      >
        <Facts
          items={[
            ["Reports that validated", pct(live.valid, 0)],
            ["Every claim cited", pct(live.cited, 0)],
            [
              "Leading hypothesis correct",
              `${Math.round(live.leadingCorrect * live.incidentRuns)} of ${live.incidentRuns}`,
            ],
            ["Time to review, p50", `${Math.round(live.p50s)} s`],
            ["Hit the latency budget", `${live.exhausted} of ${live.n}`],
            [
              "Most tokens in a run",
              `${live.maxTokens.toLocaleString("en")} of ${live.tokenLimit.toLocaleString("en")}`,
            ],
          ]}
        />
        <Table aria-label="Live provider calls">
          <TableHeader>
            <TableRow>
              <TableHead>Provider</TableHead>
              <TableHead>Model</TableHead>
              <TableHead className="text-right">Calls</TableHead>
              <TableHead className="text-right">Failed</TableHead>
              <TableHead className="text-right">p50</TableHead>
              <TableHead className="text-right">p95</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {live.providers.map((pr) => (
              <TableRow key={pr.name}>
                <TableHead scope="row">{pr.name}</TableHead>
                <TableCell className="font-mono text-xs">{pr.models.join(", ")}</TableCell>
                <TableCell className="tabular text-right">{pr.calls}</TableCell>
                <TableCell className="tabular text-right">{pr.failures}</TableCell>
                <TableCell className="tabular text-right">{pr.p50s.toFixed(1)} s</TableCell>
                <TableCell className="tabular text-right">{pr.p95s.toFixed(1)} s</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Too few runs to generalise from. Latency depended on the hosted service&apos;s load that
          day; two runs used up the {live.latencyBudgetS} s budget and finished on the deterministic
          path, which is why every report still validated.
        </p>
      </Section>
    </div>
  );
}
