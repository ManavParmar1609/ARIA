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
import { decidedByLabel } from "@/lib/decision";
import { SEVERITIES } from "@/lib/api/types";
import {
  bglResult,
  buildsResult,
  decidingResult,
  endToEndResult,
  gitlabResult,
  hadoopResult,
  hdfsResult,
  injectionResult,
  liveResult,
  openstackResult,
  postmortemsResult,
  readingResult,
  severityResult,
  TestQuestions,
  thunderbirdResult,
  ticketsResult,
} from "@/components/console/test-questions";
import { EVAL_DOC_URL, type Evaluation, type RealData, type RealLogs } from "@/lib/site-data";
import { count } from "@/lib/format";
import { NODE_LABEL } from "@/lib/steps";
import { systemName } from "@/lib/systems";
import { cn } from "@/lib/utils";

const pct = (x: number | undefined, digits = 1) =>
  x == null ? "" : `${(x * 100).toFixed(digits)}%`;

function Section({
  id,
  title,
  what,
  headline,
  intro,
  source,
  children,
}: {
  id: string;
  title: string;
  /** One sentence on what was tested. */
  what: React.ReactNode;
  /** The result, beside the strongest simple method. */
  headline?: React.ReactNode;
  /** How it was tested, in full: shown with the details. */
  intro?: React.ReactNode;
  /** Where the data and its labels come from. */
  source?: string;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="grid gap-3 rounded-lg bg-raised p-5 sm:p-6">
      <div className="grid max-w-3xl gap-1">
        {/* Clear of the sticky phone header when a link jumps here. */}
        <h3 id={id} className="scroll-mt-24 text-lg tracking-heading lg:scroll-mt-8">
          {title}
        </h3>
        <p className="text-sm text-muted-foreground">{what}</p>
      </div>
      {headline ? <p className="max-w-prose leading-relaxed">{headline}</p> : null}
      <details className="group">
        <summary className="flex min-h-6 w-fit cursor-pointer items-center text-sm font-medium text-muted-foreground hover:text-heading">
          <span className="group-open:hidden">Show details</span>
          <span className="hidden group-open:inline">Hide details</span>
        </summary>
        <div className="grid gap-5 pt-5">
          {intro ? <p className="max-w-prose text-sm text-muted-foreground">{intro}</p> : null}
          {children}
          {source ? (
            <p className="max-w-prose text-xs leading-5 text-faint">Source: {source}</p>
          ) : null}
        </div>
      </details>
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
          {/* Labels wrap rather than cut: "First assignment group" must stay readable. */}
          <span className="text-pretty text-muted-foreground">{name}</span>
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
            <TableHead className="w-24">Labelled</TableHead>
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
      title="A Hadoop file system's blocks, judged by experts"
      what="Can ARIA find the storage blocks that failed, from the log lines alone?"
      headline={hdfsResult(real)}
      source={real.citation}
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
          ["Flags that were right (precision)", pct(real.lifecycle.precision)],
          ["Failures caught, judged blocks (recall)", pct(real.lifecycle.recall)],
          ["Failures caught, all blocks (recall)", pct(real.recallAll)],
          ["Balance of the two (F1)", real.lifecycle.f1.toFixed(3)],
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
            <TableHead className="text-right">Right flags (precision)</TableHead>
            <TableHead className="text-right">Caught (recall)</TableHead>
            <TableHead className="text-right">Balance (F1)</TableHead>
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
      <p className="max-w-prose text-sm text-muted-foreground">
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
        The deployed log scan opens an incident on a burst of errors, and this log has none.
      </p>
      <p className="max-w-prose text-sm text-muted-foreground">
        A block is judged only in a window that holds its whole life, so the window length moves the
        result most (ARIA uses {real.windowMin} minutes):
      </p>
      <Table aria-label="How the real-log result depends on the window length">
        <TableHeader>
          <TableRow>
            <TableHead>Window</TableHead>
            <TableHead className="text-right">Judged</TableHead>
            <TableHead className="text-right">Right flags (precision)</TableHead>
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
      <p className="max-w-prose text-sm text-muted-foreground">
        And with the check&apos;s two settings: how often two steps&apos; counts must agree before
        they count as a pair (ARIA uses {pct(real.minSupport, 0)}), and how long it waits before
        judging a block, as the share of healthy blocks finished by then (ARIA uses{" "}
        {pct(real.settleQuantile)}). Both were chosen on this log with its labels in view:
      </p>
      <Table aria-label="How the real-log result depends on ARIA's two settings">
        <TableHeader>
          <TableRow>
            <TableHead>Pair agreement</TableHead>
            <TableHead>Healthy blocks finished</TableHead>
            <TableHead className="text-right">Judged</TableHead>
            <TableHead className="text-right">Right flags (precision)</TableHead>
            <TableHead className="text-right">Caught (recall)</TableHead>
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
              <TableCell className="tabular">{pct(row.min_support, 0)}</TableCell>
              <TableCell className="tabular">{pct(row.settle_quantile)}</TableCell>
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

const LABELS: Record<string, string> = {
  normal: "Healthy",
  machine_down: "Machine down",
  network_disconnection: "Network disconnection",
  disk_full: "Disk full",
};
const MODES: Record<string, string> = {
  resourcemanager_unreachable: "ResourceManager unreachable",
  hdfs_lease_renewal: "HDFS lease renewal",
  component_errors: "Errors in one component",
  none: "No hypothesis held",
};
const GAIA_NAMES: Record<string, string> = {
  arangodb: "ArangoDB",
  clickhouse: "ClickHouse",
  kafka: "Kafka",
  redis: "Redis",
  tengine: "Tengine",
};
const SLA_BASELINES: Record<string, string> = {
  first_assignment_group: "First assignment group's breach rate",
  category: "Category's breach rate",
  location: "Location's breach rate",
  priority_at_open: "Opening priority's breach rate",
};
const SOURCES: Record<string, string> = {
  bipia: "BIPIA",
  injecagent: "InjecAgent",
  cyberseceval: "CyberSecEval 2",
  tensor_trust: "Tensor Trust",
  giskard: "Giskard",
  jailbreaks: "Jailbreaks in the wild",
};

function MethodTable({
  label,
  head,
  rows,
}: {
  label: string;
  head: string[];
  rows: { name: string; cells: string[]; strong?: boolean }[];
}) {
  return (
    <Table aria-label={label}>
      <TableHeader>
        <TableRow>
          {head.map((h, i) => (
            <TableHead key={h} className={i > 0 ? "text-right" : undefined}>
              {h}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.name} className={cn(row.strong && "bg-highlight/40")}>
            <TableHead scope="row" className={cn(row.strong && "text-foreground")}>
              {row.name}
            </TableHead>
            {row.cells.map((cell, i) => (
              <TableCell key={i} className="tabular text-right">
                {cell}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/**
 * The other real-data evaluations: BGL windows, Hadoop jobs, OpenStack runs, tickets, GitLab.com's
 * incidents, cloud post-mortems and injection benchmarks.
 */
function MoreRealSections({ more, data }: { more: RealData; data: Evaluation }) {
  const {
    bgl,
    thunderbird: tb,
    builds,
    hadoop,
    openstack,
    tickets,
    gitlab,
    postmortems,
    injection,
  } = more;
  const n = (x: number) => x.toLocaleString("en");
  const sev = (m: typeof bgl.aria) => [
    pct(m.accuracy),
    m.macroF1.toFixed(3),
    `${n(m.severeMissed)} of ${n(bgl.severe)}`,
    `${n(m.quietPaged)} of ${n(bgl.quiet)}`,
  ];
  const job = (d: typeof hadoop.aria) => [
    `${d.caught} of ${d.failed} (${pct(d.recall, 0)})`,
    `${d.falseAlarms} of ${d.healthy}`,
  ];
  const ticket = (m: typeof tickets.aria) => [
    pct(m.accuracy),
    m.macroF1.toFixed(3),
    `${m.severeMissed} of ${tickets.severe}`,
  ];
  const labelOrder = Object.keys(LABELS).filter((k) => k in hadoop.byLabel);
  const caught = (d: typeof openstack.ariaSilent) =>
    `${n(d.caught)} of ${n(d.of)} (${pct(d.share, 0)})`;
  const rank = (d: typeof openstack.ranking.aria) =>
    `${d.value.toFixed(3)} (${(d.ci[0] ?? 0).toFixed(2)}–${(d.ci[1] ?? 0).toFixed(2)})`;
  type Memory = typeof gitlab.service;
  const recall = (pick: (m: Memory) => Memory["aria"]) =>
    [gitlab.service, gitlab.cause].flatMap((by) => [pct(pick(by).hit3), pct(pick(by).hit1)]);
  const fusedLoses = gitlab.service.bm25.hit3 > gitlab.service.aria.hit3;
  const recalled = (pick: (m: Memory) => Memory["aria"]) =>
    [postmortems.cause, postmortems.fix].flatMap((by) => [pct(pick(by).hit3), pct(pick(by).hit1)]);
  const clouds = Object.entries(postmortems.byCloud)
    .map(([cloud, k]) => `${n(k)} from ${cloud}`)
    .join(", ");
  return (
    <>
      <Section
        id="ev-bgl"
        title="A supercomputer's own alarm tags"
        what="Does ARIA rate each stretch of BlueGene/L's whole log as seriously as its administrators' alert tags do?"
        headline={bglResult(more.bgl)}
        source={bgl.citation}
        intro={
          <>
            {n(bgl.lines)} BlueGene/L lines over {Math.round(bgl.days)} days, cut into{" "}
            {n(bgl.windows)} {bgl.windowMin}-minute windows. Each window&apos;s label comes from the
            alert tags the machine&apos;s administrators gave its lines, through the rubric that
            labels ARIA&apos;s BGL scenarios. ARIA rates each window from its lines alone; the tags
            are removed first.
          </>
        }
      >
        <Facts
          items={[
            ["Windows", n(bgl.windows)],
            ["Right level (accuracy)", pct(bgl.aria.accuracy)],
            ["Balance across levels (macro-F1)", bgl.aria.macroF1.toFixed(3)],
            ["Severe windows rated minor", `${n(bgl.aria.severeMissed)} of ${n(bgl.severe)}`],
            ["Quiet windows paged", `${n(bgl.aria.quietPaged)} of ${n(bgl.quiet)}`],
            [
              `Short list held the right level (coverage; promised ${Math.round(bgl.targetCoverage * 100)}%)`,
              pct(bgl.coverage),
            ],
          ]}
        />
        <MethodTable
          label="Severity on the BGL windows, by method"
          head={[
            "Method",
            "Right level (accuracy)",
            "Balance (macro-F1)",
            "Serious rated minor",
            "Quiet paged",
          ]}
          rows={[
            { name: "ARIA (rules, model and policy)", cells: sev(bgl.aria), strong: true },
            { name: "The rules alone", cells: sev(bgl.rules) },
            { name: "The model alone", cells: sev(bgl.model) },
            { name: "Keyword categories", cells: sev(bgl.keyword) },
            { name: "Highest log level", cells: sev(bgl.highestLevel) },
            { name: "The commonest label", cells: sev(bgl.majority) },
          ]}
        />
        <p className="max-w-prose text-sm text-muted-foreground">
          The model learned from samples built from real lines, and on this log
          {bgl.rules.macroF1 > bgl.aria.macroF1
            ? " ARIA's rules alone did better than its rules and model together"
            : " the rules and model together did at least as well as the rules alone"}
          . {pct(bgl.overlapShare, 0)} of these lines carry a message that also appears in the
          2,000-line sample the scenarios are built from.
        </p>
      </Section>

      <Section
        id="ev-thunderbird"
        title="A second supercomputer's alarm tags"
        what={`The same test on ${Math.round(tb.days / 7)} weeks of the Thunderbird cluster's log, which nothing was tuned on.`}
        headline={thunderbirdResult(more)}
        intro={
          <>
            {n(tb.lines)} Thunderbird lines over {Math.round(tb.days)} days, cut into{" "}
            {n(tb.windows)} {tb.windowMin}-minute windows; {n(tb.alertLines)} of the lines carry an
            alert tag from the machine&apos;s administrators, and each window&apos;s label comes
            from those tags. ARIA rates each window from its lines alone; the tags are removed
            first.
          </>
        }
        source={tb.citation}
      >
        <MethodTable
          label="Severity on the Thunderbird windows, by method"
          head={["Method", "Right level (accuracy)", "Quiet windows paged"]}
          rows={[
            {
              name: "ARIA (rules, model and policy)",
              cells: [pct(tb.aria.accuracy), `${n(tb.aria.quietPaged)} of ${n(tb.quiet)}`],
              strong: true,
            },
            {
              name: "The rules alone",
              cells: [pct(tb.rules.accuracy), `${n(tb.rules.quietPaged)} of ${n(tb.quiet)}`],
            },
            {
              name: "Keyword categories",
              cells: [pct(tb.keyword.accuracy), `${n(tb.keyword.quietPaged)} of ${n(tb.quiet)}`],
            },
            {
              name: "The commonest label",
              cells: [pct(tb.majority.accuracy), `${n(tb.majority.quietPaged)} of ${n(tb.quiet)}`],
            },
          ]}
        />
        <p className="max-w-prose text-sm text-muted-foreground">
          The rules that fired most often on the quiet windows ARIA paged:{" "}
          {tb.pagedBy
            .map(([rule, windows]) => `${rule.replaceAll("_", " ")} (${n(windows)} windows)`)
            .join(", ")}
          .
        </p>
      </Section>

      <Section
        id="ev-hadoop"
        title="Hadoop jobs with injected failures"
        what="Can ARIA tell the jobs that failed from the healthy ones, and say how they failed?"
        headline={hadoopResult(more)}
        source={hadoop.citation}
        intro={
          <>
            Every container log of {hadoop.jobs} MapReduce jobs ({n(hadoop.lines)} lines), each
            triaged offline from start to finish as one run. Some ran normally; in the rest a
            failure was injected while they ran. A job counts as flagged when ARIA rates it SEV1 to
            SEV3.
          </>
        }
      >
        <MethodTable
          label="Failed and healthy Hadoop jobs flagged, by method"
          head={["Method", "Failed jobs flagged", "Healthy jobs flagged"]}
          rows={[
            { name: "ARIA, end to end", cells: job(hadoop.aria), strong: true },
            { name: "Any ERROR or FATAL line", cells: job(hadoop.anyError) },
            { name: "Keyword categories", cells: job(hadoop.keyword) },
          ]}
        />
        <MethodTable
          label="ARIA's severity and leading hypothesis for each kind of Hadoop job"
          head={["Label", "Jobs", "SEV1", "SEV2", "SEV3", "SEV4", "Leading hypothesis"]}
          rows={labelOrder.map((k) => {
            const sevs = hadoop.severityByLabel[k] ?? {};
            const [mode] = Object.entries(hadoop.leadingByLabel[k] ?? {});
            return {
              name: LABELS[k] ?? k,
              cells: [
                String(hadoop.byLabel[k]),
                ...SEVERITIES.map((s) => String(sevs[s] ?? 0)),
                mode ? `${MODES[mode[0]] ?? mode[0]} (${mode[1]})` : "",
              ],
            };
          })}
        />
        <p className="max-w-prose text-sm text-muted-foreground">
          ARIA&apos;s catalog has a failure mode for tasks that cannot reach the ResourceManager and
          one for HDFS lease renewal, but none for a full disk.
        </p>
      </Section>

      <Section
        id="ev-openstack"
        title="OpenStack runs with injected bugs"
        what="Can ARIA tell the runs a bug broke, including the ones that failed silently?"
        headline={openstackResult(more)}
        source={openstack.citation}
        intro={
          <>
            {n(openstack.experiments)} runs of an OpenStack cloud ({n(openstack.lines)} lines of
            service logs), each with one bug injected into Nova, Cinder or Neutron while a workload
            created and used VMs, volumes and networks. {n(openstack.failed)} runs failed,{" "}
            {n(openstack.silent)} of them with no API error to tell the user. Each run was triaged
            offline from start to finish; a run counts as flagged when ARIA rates it SEV1 to SEV3,
            and as paged at SEV1 or SEV2.
          </>
        }
      >
        <MethodTable
          label="Failed and healthy OpenStack runs flagged, by method"
          head={["Method", "Failed runs flagged", "Healthy runs flagged"]}
          rows={[
            { name: "ARIA, end to end", cells: job(openstack.aria), strong: true },
            { name: "ARIA, paging only (SEV1-2)", cells: job(openstack.paged) },
            { name: "ARIA's rules alone", cells: job(openstack.rules) },
            { name: "Any ERROR or CRITICAL line", cells: job(openstack.anyError) },
            { name: "Keyword categories", cells: job(openstack.keyword) },
          ]}
        />
        <MethodTable
          label="Failed OpenStack runs flagged, by whether an API error reported them"
          head={["Failed runs", "ARIA", "Any ERROR or CRITICAL line"]}
          rows={[
            {
              name: "Reported by an API error",
              cells: [caught(openstack.ariaReported), caught(openstack.errorReported)],
            },
            {
              name: "Silent: no API error",
              cells: [caught(openstack.ariaSilent), caught(openstack.errorSilent)],
            },
          ]}
        />
        <MethodTable
          label="How well each score ranks failed OpenStack runs above healthy ones (AUROC)"
          head={[
            "Score (AUROC; 0.5 is a coin flip)",
            "Every run",
            "Silent failures against healthy runs",
          ]}
          rows={[
            {
              name: "ARIA's probability of SEV1-2",
              cells: [rank(openstack.ranking.aria), rank(openstack.ranking.ariaSilent)],
              strong: true,
            },
            {
              name: "ERROR and CRITICAL lines, counted",
              cells: [rank(openstack.ranking.errors), rank(openstack.ranking.errorsSilent)],
            },
          ]}
        />
        <p className="max-w-prose text-sm text-muted-foreground">
          ARIA was unsure of {n(openstack.unsure)} of the {n(openstack.experiments)} runs and sent
          them to a reviewer at the most serious level on their short list. An AUROC of 0.5 is
          chance. ARIA&apos;s only OpenStack failure mode, from a 2,000-line sample of another
          deployment, is a missing image-cache file, and its model learned from samples built from
          real lines rather than from runs like these.
        </p>
      </Section>

      <Section
        id="ev-builds"
        title="Failed CI builds"
        what="Do the lines ARIA keeps as evidence include the reason a build failed?"
        headline={buildsResult(more)}
        intro={
          <>
            {n(builds.builds)} failed builds in {builds.languages} programming languages, each with
            the lines a person marked as the reason it failed. Build logs are not what ARIA was
            built for: they have no timestamps, servers or levels. ARIA kept{" "}
            {builds.meanKept.toFixed(1)} lines per build on average as evidence; each simple method
            keeps the same number from the same log.
          </>
        }
        source={builds.citation}
      >
        <MethodTable
          label="Builds whose kept lines include the marked reason, by method"
          head={["Method", "Builds where a kept line holds the reason"]}
          rows={[
            { name: "ARIA, end to end", cells: [pct(builds.aria.rate)], strong: true },
            { name: "The last error lines", cells: [pct(builds.lastErrorLines.rate)] },
            { name: "The last lines", cells: [pct(builds.lastLines.rate)] },
            { name: "Lines picked at random", cells: [pct(builds.randomLines.rate)] },
          ]}
        />
      </Section>

      <Section
        id="ev-tickets"
        title="A service desk's tickets"
        what="Can ARIA set a ticket's priority when it opens, and spot the ones that will miss their deadline?"
        headline={ticketsResult(more)}
        source={tickets.citation}
        intro={
          <>
            {n(tickets.incidents)} real tickets with anonymised codes. The ticket model trains on
            the oldest and is scored on the newest {n(tickets.test)}, from the fields each ticket
            had when it opened. {pct(tickets.sameAsAtOpen)} of them ended at the priority they
            opened with.
          </>
        }
      >
        <MethodTable
          label="Final priority of the newest tickets, by method"
          head={[
            "Method",
            "Right priority (accuracy)",
            "Balance (macro-F1)",
            "Priority 1-2 rated 3-4",
          ]}
          rows={[
            {
              name: "ARIA (the learned impact x urgency matrix)",
              cells: ticket(tickets.aria),
              strong: true,
            },
            { name: "The ticket model alone", cells: ticket(tickets.modelOnly) },
            { name: "The priority it opened with", cells: ticket(tickets.atOpen) },
            { name: "The commonest priority", cells: ticket(tickets.majority) },
          ]}
        />
        <div className="grid max-w-2xl gap-3">
          <h4 className="text-lg tracking-heading">SLA breach risk, AUROC</h4>
          <Bars
            label="How well each method ranks the tickets that breached their SLA"
            format={(v) => v.toFixed(3)}
            rows={[
              ["ARIA's SLA model", tickets.sla.auroc],
              ...Object.entries(tickets.sla.baselines).map(
                ([k, v]) => [SLA_BASELINES[k] ?? k, v] as [string, number],
              ),
            ]}
          />
          <p className="text-sm text-muted-foreground">
            {pct(tickets.sla.breachRate)} of the {n(tickets.sla.n)} tickets breached their SLA. 0.5
            is chance. {tickets.foreseen === 0 ? "None" : tickets.foreseen} of the{" "}
            {tickets.escalated} tickets raised after they opened{" "}
            {tickets.foreseen === 1 ? "was" : "were"} foreseen.
          </p>
        </div>
      </Section>

      <Section
        id="ev-gitlab"
        title="GitLab.com's incidents"
        what="When an incident comes in, does ARIA find past ones on the same service, or with the same cause?"
        headline={gitlabResult(more)}
        source={gitlab.citation}
        intro={
          <>
            GitLab runs GitLab.com in the open: its {n(gitlab.incidents)} production incidents are
            public, labelled by the responders with the service that failed and, after review, the
            root cause. The incident library holds the {n(gitlab.memory)} opened before{" "}
            {gitlab.cutoff.slice(0, 4)}, from their titles and descriptions. Each of the{" "}
            {n(gitlab.later)} later incidents asks for similar past ones from its title alone; a hit
            is a past incident with the same label among the first {count(gitlab.top)}. Labels never
            enter the index or the query.
          </>
        }
      >
        <MethodTable
          label="Similar past GitLab.com incidents, by method"
          head={[
            "Method",
            `Same service, first ${gitlab.top}`,
            "Same service, first",
            `Same root cause, first ${gitlab.top}`,
            "Same root cause, first",
          ]}
          rows={[
            {
              name: "ARIA (BM25 and embeddings, fused by rank)",
              cells: recall((m) => m.aria),
              strong: true,
            },
            { name: "BM25 alone", cells: recall((m) => m.bm25) },
            { name: "The embeddings alone", cells: recall((m) => m.embeddings) },
            { name: "Past incidents picked at random", cells: recall((m) => m.random) },
            { name: "Always the commonest label", cells: recall((m) => m.commonest) },
          ]}
        />
        <p className="max-w-prose text-sm text-muted-foreground">
          {n(gitlab.service.aria.queries)} later incidents name a service and{" "}
          {n(gitlab.cause.aria.queries)} a root cause.{" "}
          {fusedLoses
            ? "BM25 alone did better than the fused index: the embeddings here are the offline ones, fitted on these incidents' own words, and they cost recall. "
            : "The embeddings here are the offline ones, fitted on these incidents' own words. "}
          The issues are a live source; this is the snapshot of {gitlab.snapshot}.
        </p>
      </Section>

      <Section
        id="ev-postmortems"
        title="Three clouds' post-mortems"
        what="Does ARIA find past post-mortems with the same root cause, or the same fix?"
        headline={postmortemsResult(more)}
        source={postmortems.citation}
        intro={
          <>
            {n(postmortems.postmortems)} public post-mortems ({clouds}), each structured by
            researchers with its root cause and the fixes that ended it. The incident library holds
            the {n(postmortems.memory)} post-mortems of incidents before{" "}
            {postmortems.cutoff.slice(0, 4)}, from their whole write-ups. Each of the{" "}
            {n(postmortems.later)} later ones asks for similar past incidents from its title and
            summary of impact; a hit is a past incident among the first {count(postmortems.top)}{" "}
            with the same specific root cause, or fixed the same way.
          </>
        }
      >
        <MethodTable
          label="Similar past cloud incidents, by method"
          head={[
            "Method",
            `Same cause, first ${postmortems.top}`,
            "Same cause, first",
            `Same fix, first ${postmortems.top}`,
            "Same fix, first",
          ]}
          rows={[
            {
              name: "ARIA (BM25 and embeddings, fused by rank)",
              cells: recalled((m) => m.aria),
              strong: true,
            },
            { name: "BM25 alone", cells: recalled((m) => m.bm25) },
            { name: "The embeddings alone", cells: recalled((m) => m.embeddings) },
            { name: "Past incidents picked at random", cells: recalled((m) => m.random) },
            { name: "Always the commonest label", cells: recalled((m) => m.commonest) },
          ]}
        />
        <p className="max-w-prose text-sm text-muted-foreground">
          A summary of impact says what customers saw, which seldom says what broke, and a few
          causes and fixes cover most incidents, so past incidents at random already share a label
          with many. The fixes are sorted into kinds by the words the researchers used;{" "}
          {pct(postmortems.fixLabelsSorted, 0)} of them fall into one.
        </p>
      </Section>

      <Section
        id="ev-injection"
        title="Public prompt-injection attacks"
        what="Does ARIA set aside log lines written to talk it out of an incident, when someone else wrote them?"
        headline={injectionResult(data, more)}
        intro={
          <>
            {n(injection.attacks)} attacks from {count(injection.sources.length)} public benchmarks
            the detector was never tuned on, each hidden in a log line and parsed on its own. The
            detector is the first of several layers: a line it misses still reaches a model only
            fenced as evidence, and nothing is sent before approval.
          </>
        }
      >
        <Facts
          items={[
            ["Attacks", n(injection.attacks)],
            ["Caught", pct(injection.rate)],
            ["Benign look-alikes flagged", pct(injection.benign.rate)],
            [
              `Real log lines flagged, of ${n(injection.realLines)}`,
              injection.realFlagged === 0 ? "None" : n(injection.realFlagged),
            ],
          ]}
        />
        <div className="grid max-w-2xl gap-3">
          <Bars
            label="Share of each benchmark's attacks the detector caught"
            rows={injection.sources.map(
              (s) => [SOURCES[s.key] ?? s.key, s.rate] as [string, number],
            )}
          />
          <p className="text-sm text-muted-foreground">
            It catches instructions phrased as overrides, role play and markup, and misses attacks
            phrased as ordinary requests, which no pattern can tell from a log message.
          </p>
        </div>
      </Section>
    </>
  );
}

export function Evals({
  data,
  real,
  more,
}: {
  data: Evaluation;
  real?: RealLogs;
  more?: RealData;
}) {
  const s = data.severity;
  const p = data.pipeline;
  const r = data.robustness;
  const live = data.live;
  const stages = Object.entries(p.stageP50)
    .map(([step, ms]) => [NODE_LABEL[step] ?? step, ms] as [string, number])
    .sort((a, b) => b[1] - a[1]);
  return (
    <div className="grid gap-12">
      <PageHeader
        title="Test results"
        description={
          <>
            How ARIA was tested, in four plain questions, with the simplest methods it should beat
            beside it, including where they win. Measured on {data.createdAt.slice(0, 10)}, and
            anyone can measure them again from the source code.{" "}
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

      {more ? <TestQuestions data={data} real={real} more={more} /> : null}

      <section aria-labelledby="ev-real-data" className="grid gap-4">
        <div className="grid max-w-3xl gap-2 border-t border-rule pt-6">
          <h2 id="ev-real-data" className="text-xl tracking-heading">
            Each test on real data
          </h2>
          <p className="text-muted-foreground">
            Logs, jobs, tickets, incidents and attacks, with the labels their owners gave them. Open
            a card for its tables, intervals, method and source.
          </p>
        </div>
        {real ? <RealSection real={real} /> : null}
        {more ? <MoreRealSections more={more} data={data} /> : null}
      </section>

      <section aria-labelledby="ev-built" className="grid gap-4">
        <div className="grid max-w-3xl gap-2 border-t border-rule pt-6">
          <h2 id="ev-built" className="text-xl tracking-heading">
            Each test on built samples
          </h2>
          <p className="max-w-prose text-muted-foreground">
            Each sample is real Loghub log lines arranged into an incident, so these results are not
            accuracy on production incidents.
          </p>
        </div>
        <Section
          id="ev-severity"
          title="Severity on built samples"
          what="Real log lines composed into incidents, each given a level by a written policy."
          headline={severityResult(data)}
          intro={`${s.n} labelled windows. ARIA's policy against simpler methods on the same windows.`}
        >
          <Facts
            items={[
              ["Right level (accuracy)", pct(s.accuracy)],
              ["95% interval", `${pct(s.ci[0] ?? 0)} to ${pct(s.ci[1] ?? 0)}`],
              ["Balance across levels (macro-F1)", s.macroF1.toFixed(3)],
              ["Agreement, near misses counting half (weighted kappa)", s.kappa.toFixed(3)],
              ["Serious rated minor (SEV1-2 as SEV3-4)", pct(s.severeUnderTriage)],
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
                <TableHead className="text-right">Right flags (precision)</TableHead>
                <TableHead className="text-right">Caught (recall)</TableHead>
                <TableHead className="text-right">Balance (F1)</TableHead>
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
          title="Knowing when not to decide"
          what="Does ARIA's confidence mean what it says, and does it pass the hard ones to a person?"
          headline={decidingResult(data)}
          intro="A confident wrong answer is worse than a flagged one. These measure whether ARIA's confidence means what it says."
        >
          <Facts
            items={[
              ["Gap between confidence and hit rate (calibration error)", s.ece.toFixed(3)],
              ["Probability error (Brier score; 0 is perfect)", s.brier.toFixed(3)],
              [
                `Short list held the right level (coverage; promised ${Math.round(s.targetCoverage * 100)}%)`,
                pct(s.coverage),
              ],
              ["Short list held the right level, with safety floors", pct(s.coverageWithFloors)],
              ["Levels on the short list, on average", s.setSize.toFixed(3)],
              ["Error as ARIA decides more alone (area under risk-coverage)", s.aurc.toFixed(3)],
            ]}
          />
          <div className="grid gap-8 xl:grid-cols-2">
            <RiskCoverageChart
              points={s.riskCoverage}
              operating={{ coverage: s.autoDecided, accuracy: s.accuracyWhenAuto }}
            />
            <div className="grid content-start gap-3 text-sm">
              <p>
                ARIA decided{" "}
                <span className="font-medium text-foreground">{pct(s.autoDecided)}</span> of windows
                alone, at {pct(s.accuracyWhenAuto)} accuracy. Of the rest, which it sent to review,
                its own guess was right {pct(s.accuracyWhenFlagged)} of the time.
              </p>
              <Bars
                label="Who decided"
                rows={Object.entries(s.decidedBy).map(
                  ([k, v]) => [decidedByLabel(k), v] as [string, number],
                )}
                max={s.n}
                format={(v) => `${v}`}
              />
            </div>
          </div>
        </Section>

        <Section
          id="ev-systems"
          title="By log format"
          what="The same severity test, split by the system each log came from."
          intro="Labels come from the scenario policy, except BlueGene/L, which uses its real alert tags."
        >
          <Table aria-label="Severity accuracy by system">
            <TableHeader>
              <TableRow>
                <TableHead>System</TableHead>
                <TableHead className="text-right">Windows</TableHead>
                <TableHead className="text-right">Right level (accuracy)</TableHead>
                <TableHead className="text-right">Serious rated minor</TableHead>
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
          title="End to end on built samples"
          what="Each run goes through every step, offline, up to the review."
          headline={endToEndResult(data)}
          intro={`${p.n} runs through the whole graph, offline, to the review pause.`}
        >
          <Facts
            items={[
              ["Reports that passed the citation check", pct(p.valid, 0)],
              ["Every claim cited", pct(p.cited, 0)],
              ["Right past incident in the top three", pct(p.recallAt3, 0)],
              ["Leading cause right", pct(p.leadingCorrect, 0)],
              [
                "False alarms on quiet windows",
                `${Math.round(p.falseAlarms * p.quietRuns)} of ${p.quietRuns}`,
              ],
              [
                "Ready for review, median / slowest 5%",
                `${p.p50s.toFixed(2)} / ${p.p95s.toFixed(2)} s`,
              ],
            ]}
          />
          <div className="grid gap-3">
            <h4 className="font-sans text-sm font-semibold">Median time per step</h4>
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
          title="Reading logs, and hostile input"
          what="Does ARIA group log lines the way people did, and stay standing on broken or hostile lines?"
          headline={readingResult(data)}
          intro={`Template grouping against Loghub's and GAIA's hand labels, and ${r.edgeN.toLocaleString("en")} hostile or broken inputs.`}
        >
          <div className="grid gap-8 xl:grid-cols-2">
            <div className="grid content-start gap-3">
              <h4 className="font-sans text-sm font-semibold">
                Grouping accuracy by system (mean {data.parsing.meanAccuracy.toFixed(3)})
              </h4>
              <Bars
                label="Grouping accuracy by system"
                rows={Object.entries(data.parsing.bySystem)
                  .map(([k, v]) => [systemName(k), v.grouping_accuracy] as [string, number])
                  .sort((a, b) => b[1] - a[1])}
                format={(v) => v.toFixed(3)}
              />
              <p className="text-sm text-muted-foreground">
                On GAIA&apos;s {data.parsing.gaia.lines.toLocaleString("en")} labelled lines from{" "}
                {data.parsing.gaia.systems} systems, the mean is{" "}
                {data.parsing.gaia.meanAccuracy.toFixed(3)}:{" "}
                {data.parsing.gaia.knownAccuracy.toFixed(3)} on the Loghub systems and{" "}
                {data.parsing.gaia.newAccuracy.toFixed(3)} on{" "}
                {data.parsing.gaia.newSystems.map((k) => GAIA_NAMES[k] ?? k).join(", ")}, which ARIA
                has no format or settings for.
              </p>
            </div>
            <div className="grid content-start gap-3">
              <h4 className="font-sans text-sm font-semibold">
                Attacks quarantined, by family (overall {pct(r.attackRecall)})
              </h4>
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
          title="With a language model"
          what={`The built-sample runs again, with ${live.answeredBy} writing the reports.`}
          headline={liveResult(data)}
          intro={`${live.n} runs through ${live.answeredBy}, ${live.createdAt.slice(0, 10)}.`}
        >
          <Facts
            items={[
              ["Reports that passed the citation check", pct(live.valid, 0)],
              ["Every claim cited", pct(live.cited, 0)],
              [
                "Leading hypothesis correct",
                `${Math.round(live.leadingCorrect * live.incidentRuns)} of ${live.incidentRuns}`,
              ],
              ["Ready for review, median", `${Math.round(live.p50s)} s`],
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
          <p className="max-w-prose text-sm text-muted-foreground">
            Too few runs to generalise from. Latency depended on the hosted service&apos;s load that
            day.{" "}
            {live.exhausted > 0
              ? `${live.exhausted === 1 ? "One run" : `${live.exhausted} runs`} used up the ${live.latencyBudgetS} s budget after the model had written ${live.exhausted === 1 ? "its report" : "their reports"}, so only the steps after it fell back to the deterministic path. `
              : `No run used up the ${live.latencyBudgetS} s budget. `}
            {live.writtenByModel === live.n
              ? "Every report was written by the model"
              : `The model wrote ${live.writtenByModel} of ${live.n} reports`}
            {live.valid === 1 ? ", and every one validated." : "."}
          </p>
        </Section>
      </section>
    </div>
  );
}
