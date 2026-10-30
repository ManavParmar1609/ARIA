import { RollingNumber } from "@/components/aria/rolling-number";
import { BaselineChart, RiskCoverageChart } from "@/components/site/charts";
import { EVAL_DOC_URL, type Evaluation } from "@/lib/site-data";

const pct = (x: number, digits = 1) => `${(x * 100).toFixed(digits)}%`;

function Stat({ value, children }: { value: string; children: React.ReactNode }) {
  return (
    <div className="grid content-start gap-2 border-t border-rule pt-4">
      <dt className="order-2 text-sm text-muted-foreground">{children}</dt>
      <dd className="stat order-1 text-4xl">{value}</dd>
    </div>
  );
}

/** A headline number: large, in ink, with its name and what it was measured on. */
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

const CARD = "rounded-lg bg-raised p-5 sm:p-8";

export function Results({ data }: { data: Evaluation }) {
  const s = data.severity;
  const p = data.pipeline;
  const r = data.robustness;
  const live = data.live;
  const weakest = Object.entries(data.parsing.bySystem)
    .sort(([, a], [, b]) => a.grouping_accuracy - b.grouping_accuracy)
    .slice(0, 2);
  return (
    <div className="grid gap-20 lg:gap-24">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-12 lg:grid-cols-4">
        <Headline
          value={pct(s.accuracy)}
          label="Severity accuracy"
          note={`on ${s.n} held-out semi-synthetic incident windows`}
        />
        <Headline
          value={pct(p.cited, 0)}
          label="Claims cited"
          note={`across ${p.n} full offline runs, each to evidence that exists`}
        />
        <Headline
          value={`${p.p50s.toFixed(2)} s`}
          label="Median time to review"
          note="from logs to a report a person can approve, offline"
        />
        <Headline
          value={pct(r.attackRecall)}
          label="Injections quarantined"
          note={`of ${r.attacks.toLocaleString("en")} attacks; an upper bound`}
        />
      </dl>

      <div className="grid gap-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16">
        <div className="grid content-start gap-4">
          <h3 className="text-2xl tracking-heading">Severity, against simpler ways to do it</h3>
          <p className="text-muted-foreground">
            On {s.n} labelled windows, ARIA rated severity correctly {pct(s.accuracy)} of the time
            (95% interval {pct(s.ci[0] ?? 0)} to {pct(s.ci[1] ?? 0)}), with macro-F1{" "}
            {s.macroF1.toFixed(3)}. It rated a SEV1 or SEV2 incident as SEV3 or SEV4{" "}
            {pct(s.severeUnderTriage)} of the time.
          </p>
          <p className="text-muted-foreground">
            The model alone scores about the same, so most of the policy&apos;s value is not
            accuracy: it is knowing when not to decide. Its 90% prediction sets held the true
            severity {pct(s.coverage)} of the time, with an expected calibration error of{" "}
            {s.ece.toFixed(3)}.
          </p>
        </div>
        <BaselineChart methods={s.methods} className={CARD} />
      </div>

      <div className="grid gap-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16">
        <div className="grid content-start gap-4">
          <h3 className="text-2xl tracking-heading">Deciding alone, and knowing when not to</h3>
          <p className="text-muted-foreground">
            ARIA decided {pct(s.autoDecided)} of windows without a person, and was right on{" "}
            {pct(s.accuracyWhenAuto)} of those. It sent the rest to review, where its own guess was
            right only {pct(s.accuracyWhenFlagged)} of the time: the hard cases went to people.
          </p>
        </div>
        <RiskCoverageChart
          points={s.riskCoverage}
          operating={{ coverage: s.autoDecided, accuracy: s.accuracyWhenAuto }}
          className={CARD}
        />
      </div>

      <div className="grid gap-8">
        <h3 className="text-2xl tracking-heading">End to end, through the whole graph</h3>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-6 md:grid-cols-3 lg:grid-cols-5">
          <Stat value={pct(p.valid, 0)}>of {p.n} reports passed validation</Stat>
          <Stat value={pct(p.cited, 0)}>had every claim cite existing evidence</Stat>
          <Stat value={pct(p.recallAt3, 0)}>found a matching past incident in the top 3</Stat>
          <Stat value={`${Math.round(p.falseAlarms * p.quietRuns)} of ${p.quietRuns}`}>
            quiet windows raised a false alarm
          </Stat>
          {/* The median is a headline above; the tail is what this row adds. */}
          <Stat value={`${p.p95s.toFixed(2)} s`}>95th percentile time to review, offline</Stat>
        </dl>
        <p className="max-w-3xl text-sm text-muted-foreground">
          These runs use the deterministic offline path (no LLM). Past incidents in memory are
          synthetic, which flatters retrieval: real incident history is messier.
        </p>
      </div>

      <div className="grid gap-10 lg:grid-cols-2 lg:gap-16">
        <div className="grid content-start gap-4">
          <h3 className="text-2xl tracking-heading">Hostile and broken input</h3>
          <p className="text-muted-foreground">
            Across {r.edgeN.toLocaleString("en")} edge-case and injection inputs the parser never
            failed, and the guard quarantined {pct(r.attackRecall)} of{" "}
            {r.attacks.toLocaleString("en")} attacks while flagging{" "}
            {r.benignFalsePositives === 0
              ? `none of ${r.benign.toLocaleString("en")} benign lines`
              : `${pct(r.benignFalsePositives)} of ${r.benign.toLocaleString("en")} benign lines`}
            . In {r.windows} incident windows with planted instructions, severity and the
            investigator&apos;s tool calls never changed, and no report repeated the injected text.
          </p>
          <p className="text-sm text-muted-foreground">
            The project wrote both the attacks and the detector, and tuned one on the other, so
            treat that recall as an upper bound.
          </p>
        </div>
        <div className="grid content-start gap-4">
          <h3 className="text-2xl tracking-heading">With a live model</h3>
          <p className="text-muted-foreground">
            In {live.n} runs through hosted NVIDIA NIM models every report still validated and cited
            its evidence, but a run took about {Math.round(live.p50s)} s, and {live.exhausted} of{" "}
            {live.n} hit the {live.latencyBudgetS} s budget and finished on the deterministic path.
            The leading hypothesis named the true cause in{" "}
            {Math.round(live.leadingCorrect * live.incidentRuns)} of {live.incidentRuns} incident
            runs.
          </p>
          <p className="text-sm text-muted-foreground">
            Models used: {live.providers.flatMap((pr) => pr.models).join(" and ")}. Too few runs to
            generalise from; latency depended on the provider&apos;s load that day.
          </p>
        </div>
      </div>

      <div className="grid gap-4 border-t border-rule pt-8 text-sm text-muted-foreground md:grid-cols-[1fr_auto] md:items-end">
        <p className="max-w-3xl">
          Data: {data.dataDescription}. Template grouping is measured on Loghub&apos;s hand-labelled
          samples ({data.parsing.systems} systems, mean {data.parsing.meanAccuracy.toFixed(3)}); it
          is weakest on{" "}
          {weakest.map(([name, v]) => `${name} (${v.grouping_accuracy.toFixed(2)})`).join(" and ")}.
          Results from commit {data.gitSha}; <code>make eval</code> reproduces them, and CI&apos;s
          smoke gate fails on a regression in severity, parsing, retrieval or reporting.
        </p>
        <a
          href={EVAL_DOC_URL}
          className="justify-self-start rounded-sm font-medium text-heading underline decoration-control underline-offset-4 hover:decoration-foreground"
        >
          Read the full evaluation
        </a>
      </div>
    </div>
  );
}
