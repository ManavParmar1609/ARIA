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
import { EVAL_DOC_URL, type Evaluation } from "@/lib/site-data";
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
        <h2 id={id} className="text-xl font-bold">
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
    <dl className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 xl:grid-cols-6">
      {items.map(([label, value]) => (
        <div key={label} className="grid content-start gap-1 border-t border-rule pt-2.5">
          <dt className="text-xs text-muted-foreground">{label}</dt>
          <dd className="tabular text-xl font-bold">{value}</dd>
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
          className="grid grid-cols-[minmax(7rem,11rem)_1fr_4rem] items-center gap-3 text-sm"
        >
          <span className="truncate text-muted-foreground">{name}</span>
          <span className="h-2.5 rounded-xs bg-sunken" aria-hidden>
            <span
              className="block h-2.5 rounded-xs bg-control"
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
                  return (
                    <TableCell
                      key={j}
                      className={cn(
                        "tabular text-center",
                        i === j && "font-bold",
                        under && n > 0 && "text-danger",
                      )}
                      style={{
                        backgroundColor:
                          n > 0
                            ? `color-mix(in oklch, var(${i === j ? "--primary" : under ? "--danger" : "--control"}) ${Math.round(8 + share * 40)}%, transparent)`
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

export function Evals({ data }: { data: Evaluation }) {
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
            Measured on {data.dataDescription}. Results from commit <code>{data.gitSha}</code>, run{" "}
            {data.createdAt.slice(0, 10)}; <code>make eval</code> reproduces them and CI fails on a
            regression.{" "}
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
          <h3 className="text-sm font-semibold">Median time per step</h3>
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
            <h3 className="text-sm font-semibold">
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
            <h3 className="text-sm font-semibold">
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
