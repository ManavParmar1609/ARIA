import type { Evaluation, RealData, RealLogs } from "@/lib/site-data";
import { cn } from "@/lib/utils";

// Test results, told as four plain questions (item 24). Each answer leads with the measure that
// matters (serious problems missed, false alarms, the right past incident found) and puts ARIA
// beside its strongest simple rivals, including where they win. Every number is computed from the
// published results, and every comparison in the words is checked against them, so a rerun of
// `make eval` can never leave a sentence saying the opposite of its numbers.

const per100 = (x: number) => Math.round(x * 100);
const count = (x: number) => x.toLocaleString("en");
const list = (items: string[]) =>
  new Intl.ListFormat("en-GB", { type: "conjunction" }).format(items);

/** Held about as often as promised: within 3 in 100 of the target, or above it. */
export const heldAsPromised = (coverage: number, target: number) => coverage >= target - 0.03;

/** "slightly better" for a small gap, "better" for a large one. */
const better = (gap: number) => (gap < 0.05 ? "slightly better" : "better");
const less = (gap: number) => (gap < 0.05 ? "Slightly less often" : "Less often");

function Question({
  id,
  question,
  answer,
  children,
}: {
  id: string;
  question: string;
  answer: string;
  children: React.ReactNode;
}) {
  // The answer's first sentence is the verdict; the figures behind it read as its detail.
  const split = /^(.+?[.!?])\s+(?=[A-Z“"])(.+)$/s.exec(answer);
  const [verdict, detail] = split ? [split[1], split[2]] : [answer, null];
  return (
    <section
      aria-labelledby={id}
      className="grid gap-5 rounded-card border border-rule bg-raised p-5 sm:p-6"
    >
      <div className="grid max-w-3xl gap-2">
        <h3 id={id} className="scroll-mt-24 text-xl leading-snug lg:scroll-mt-8">
          {question}
        </h3>
        <p className="text-lg leading-relaxed font-medium text-foreground">{verdict}</p>
        {detail ? (
          <p className="text-base leading-relaxed text-muted-foreground">{detail}</p>
        ) : null}
      </div>
      {children}
    </section>
  );
}

/** One row per log: a bar for how often the short list held the right level, and the promise. */
function Coverage({
  rows,
  target,
}: {
  rows: { name: string; detail: string; value: number }[];
  target: number;
}) {
  return (
    <ul aria-label="Short list held the right level, per 100" className="grid max-w-3xl gap-3">
      {rows.map((row) => {
        const held = heldAsPromised(row.value, target);
        return (
          <li
            key={row.name}
            className="grid gap-1.5 text-sm sm:grid-cols-[minmax(0,13rem)_1fr_7.5rem] sm:items-center sm:gap-3"
          >
            <span className="grid">
              <span>{row.name}</span>
              <span className="text-xs text-muted-foreground">{row.detail}</span>
            </span>
            <span aria-hidden className="relative h-2.5 rounded-xs bg-sunken">
              <span
                className={cn("block h-2.5 rounded-xs", held ? "bg-primary/80" : "bg-danger/70")}
                style={{ width: `${Math.min(100, row.value * 100)}%` }}
              />
              {/* The promise, as a tick across the bar. */}
              <span
                className="absolute -top-1 h-4.5 w-0.5 bg-foreground"
                style={{ left: `${target * 100}%` }}
              />
            </span>
            <span className="tabular sm:text-right">
              {per100(row.value)} of 100{" "}
              <span className="text-muted-foreground">{held ? "as promised" : "far short"}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export function unsureAnswer(
  rows: { name: string; phrase?: string; value: number }[],
  target: number,
): string {
  const held = rows.filter((r) => heldAsPromised(r.value, target)).map((r) => r.phrase ?? r.name);
  const missed = rows.filter((r) => !heldAsPromised(r.value, target));
  const promise = `${per100(target)} times in 100`;
  if (!missed.length) {
    return `Yes. Its short list of likely levels held the right one about as often as promised, ${promise}, on every log it was tested on.`;
  }
  const worst = missed.reduce((a, b) => (b.value < a.value ? b : a));
  const failed = `On ${list(missed.map((r) => r.phrase ?? r.name))}, no: there the list held the right level only ${per100(worst.value)} times in 100, so ARIA was confidently wrong.`;
  if (!held.length) return `No. ${failed}`;
  return `On ${list(held)}, yes: its short list of likely levels held the right one about as often as promised, ${promise}. ${failed}`;
}

type Method = RealData["bgl"]["aria"];

const rulesWin = ({ aria, rules }: RealData["bgl"]) =>
  rules.severeMissed <= aria.severeMissed && rules.quietPaged <= aria.quietPaged;

/** BlueGene/L: serious stretches missed and false alarms, beside ARIA's own rules alone. */
export function bglResult(bgl: RealData["bgl"]): string {
  const { aria, rules } = bgl;
  const facts = `ARIA missed ${count(aria.severeMissed)} of ${count(bgl.severe)} serious stretches and raised ${count(aria.quietPaged)} false alarms on ${count(bgl.quiet)} quiet ones.`;
  return rulesWin(bgl)
    ? `${facts} Its own rules, used alone, did better on both: ${count(rules.severeMissed)} missed and ${count(rules.quietPaged)} false alarms.`
    : `${facts} Its own rules, used alone, missed ${count(rules.severeMissed)} and raised ${count(rules.quietPaged)} false alarms.`;
}

export function alarmsAnswer(bgl: RealData["bgl"]): string {
  const { aria, majority } = bgl;
  const accuracy =
    majority.accuracy > aria.accuracy
      ? ` Always answering “quiet” is right more often (${per100(majority.accuracy)} stretches in 100, against ARIA's ${per100(aria.accuracy)}) yet misses all ${count(majority.severeMissed)} serious ones, which is why this page counts misses and false alarms rather than accuracy.`
      : "";
  return `${rulesWin(bgl) ? "Not yet as well as it should. " : ""}On a supercomputer's whole log, ${bglResult(bgl)}${accuracy}`;
}

function AlarmTable({ bgl }: { bgl: RealData["bgl"] }) {
  const rows: [string, Method][] = [
    ["ARIA", bgl.aria],
    ["ARIA's rules alone", bgl.rules],
    ["The highest log level in each stretch", bgl.highestLevel],
    ["Keyword categories", bgl.keyword],
    ["Always “quiet”", bgl.majority],
  ];
  return (
    <div className="max-w-3xl overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="pb-2 text-left text-xs text-muted-foreground">
          BlueGene/L, {count(bgl.windows)} stretches of {bgl.windowMin} minutes, rated from the
          lines alone against its administrators&apos; alert tags
        </caption>
        <thead>
          <tr className="border-b border-rule text-left text-xs text-muted-foreground">
            <th scope="col" className="py-2 pr-3 font-normal">
              Method
            </th>
            <th scope="col" className="py-2 pr-3 text-right font-normal">
              Serious stretches missed (of {count(bgl.severe)})
            </th>
            <th scope="col" className="py-2 text-right font-normal">
              False alarms on quiet ones (of {count(bgl.quiet)})
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([name, m]) => (
            <tr key={name} className="border-b border-rule/60">
              <th
                scope="row"
                className={cn("py-2 pr-3 text-left font-normal", name === "ARIA" && "font-medium")}
              >
                {name}
              </th>
              <td className="tabular py-2 pr-3 text-right">{count(m.severeMissed)}</td>
              <td className="tabular py-2 text-right">{count(m.quietPaged)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** HDFS blocks: failures caught and false alarms, beside the best standard detector. */
export function hdfsResult(real: RealLogs): string {
  const life = real.lifecycle;
  const caught = life.flagged - life.falseAlarms;
  const facts = `ARIA caught ${count(caught)} of ${count(real.judgedFailed)} failed blocks, with ${count(life.falseAlarms)} false alarms among ${count(life.healthy)} healthy ones.`;
  const best = [...real.detectors].sort(
    (a, b) => b.recall - a.recall || a.falseAlarms - b.falseAlarms,
  )[0];
  if (!best) return facts;
  const bestCaught = best.flagged - best.falseAlarms;
  return bestCaught === caught && best.falseAlarms === life.falseAlarms
    ? `${facts} The best standard detector did exactly the same.`
    : `${facts} The best standard detector (${best.label}) caught ${count(bestCaught)}, with ${count(best.falseAlarms)} false alarms.`;
}

export function hadoopResult(more: RealData): string {
  const h = more.hadoop;
  return `ARIA caught ${count(h.aria.caught)} of ${count(h.aria.failed)} failed jobs, where “any error line” caught ${count(h.anyError.caught)}; it also flagged ${count(h.aria.falseAlarms)} of ${count(h.aria.healthy)} healthy jobs, against ${count(h.anyError.falseAlarms)}.`;
}

export function openstackResult(more: RealData): string {
  const o = more.openstack;
  const unsure = o.unsure / Math.max(1, o.aria.failed + o.aria.healthy) > 0.9;
  return `ARIA flagged ${count(o.aria.caught)} of ${count(o.aria.failed)} failed runs, but also ${count(o.aria.falseAlarms)} of ${count(o.aria.healthy)} healthy ones${unsure ? ". When unsure it picks the more serious level and asks a person, and it was unsure of nearly every run" : ""}. Any error line flagged ${count(o.anyError.caught)} failed and ${count(o.anyError.falseAlarms)} healthy runs.`;
}

export function elsewhereLines(real: RealLogs | undefined, more: RealData): string[] {
  return [
    ...(real ? [`A Hadoop file system's blocks, judged by experts: ${hdfsResult(real)}`] : []),
    `Hadoop jobs with injected failures: ${hadoopResult(more)}`,
    `OpenStack runs with injected bugs: ${openstackResult(more)}`,
  ];
}

export function memoryAnswer(more: RealData): string {
  const { aria, bm25 } = more.gitlab.service;
  const facts = `For ${count(aria.queries)} of GitLab.com's real incidents, a past incident on the same service was among ARIA's top three ${per100(aria.hit3)} times in 100, and among plain keyword search's ${per100(bm25.hit3)} times.`;
  return bm25.hit3 > aria.hit3
    ? `${less(bm25.hit3 - aria.hit3)} than plain keyword search. ${facts}`
    : `As often as plain keyword search, or more. ${facts}`;
}

function MemoryRows({ data, more }: { data: Evaluation; more: RealData }) {
  const g = more.gitlab.service;
  const p = more.postmortems.cause;
  const rows: { name: string; aria: number; keyword: number; meaning: number; chance: number }[] = [
    {
      name: "GitLab.com incidents, same service",
      aria: g.aria.hit3,
      keyword: g.bm25.hit3,
      meaning: g.embeddings.hit3,
      chance: g.random.hit3,
    },
    {
      name: "Cloud post-mortems, same root cause",
      aria: p.aria.hit3,
      keyword: p.bm25.hit3,
      meaning: p.embeddings.hit3,
      chance: p.random.hit3,
    },
  ];
  return (
    <div className="grid max-w-3xl gap-3">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="pb-2 text-left text-xs text-muted-foreground">
            The right kind of past incident among the top three, per 100 questions
          </caption>
          <thead>
            <tr className="border-b border-rule text-left text-xs text-muted-foreground">
              <th scope="col" className="py-2 pr-3 font-normal">
                Test
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-normal">
                ARIA
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-normal">
                Keyword search
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-normal">
                Search by meaning
              </th>
              <th scope="col" className="py-2 text-right font-normal">
                A random pick
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.name} className="border-b border-rule/60">
                <th scope="row" className="py-2 pr-3 text-left font-normal">
                  {row.name}
                </th>
                <td className="tabular py-2 pr-3 text-right font-medium">{per100(row.aria)}</td>
                <td className="tabular py-2 pr-3 text-right">{per100(row.keyword)}</td>
                <td className="tabular py-2 pr-3 text-right">{per100(row.meaning)}</td>
                <td className="tabular py-2 text-right">{per100(row.chance)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-sm text-muted-foreground">
        On built samples the right past incident was in the top three{" "}
        {per100(data.pipeline.recallAt3)} times in 100, but those samples share their patterns with
        the incidents ARIA&apos;s memory starts with, so that is the easy case.
      </p>
    </div>
  );
}

export function thunderbirdResult(more: RealData): string {
  const t = more.thunderbird;
  return `ARIA raised false alarms on ${count(t.aria.quietPaged)} of ${count(t.quiet)} quiet stretches, and its short list held the right level only ${per100(t.coverage)} times in 100. Its rules count error lines, warning words and new messages in each stretch, and none of them knows what is routine for a system ARIA has not seen before; on Thunderbird those lines are routine.`;
}

export function buildsResult(more: RealData): string {
  const b = more.builds;
  const gap = b.lastErrorLines.rate - b.aria.rate;
  return `The lines ARIA kept held the reason a build failed in ${per100(b.aria.rate)} builds in 100. ${
    gap > 0
      ? `Simply keeping the last error lines did ${better(gap)}: ${per100(b.lastErrorLines.rate)} in 100.`
      : `Simply keeping the last error lines found ${per100(b.lastErrorLines.rate)} in 100.`
  }`;
}

export function injectionResult(data: Evaluation, more: RealData): string {
  const i = more.injection;
  const r = data.robustness;
  return `ARIA's line filter set aside ${count(i.caught)} of ${count(i.attacks)} attacks written by others, against ${per100(r.attackRecall)} in 100 of the attacks this project wrote and tuned it on, and ${i.realFlagged ? count(i.realFlagged) : "none"} of ${count(i.realLines)} real log lines.`;
}

const INJECTION_WHY =
  "Attacks phrased as ordinary requests can't be told from a log message by any pattern. A line it misses still reaches a model only fenced as evidence, can't move the severity outside the short list, and nothing is sent before a person approves.";

export function shortfallLines(data: Evaluation, more: RealData): string[] {
  return [
    `Thunderbird, a second supercomputer: ${thunderbirdResult(more)}`,
    `Build logs from failed CI builds, which ARIA was not built for (no timestamps, servers or levels, and nothing was tuned on them): ${buildsResult(more)}`,
    `Public prompt-injection attacks: ${injectionResult(data, more)} ${INJECTION_WHY}`,
  ];
}

const FIELD_NAMES: Record<string, string> = {
  first_assignment_group: "the first assigned team",
  category: "the category",
  location: "the location",
  priority_at_open: "the priority at opening",
};

export function ticketsResult(more: RealData): string {
  const t = more.tickets;
  const same =
    t.aria.accuracy === t.atOpen.accuracy
      ? "exactly as often as keeping the priority given at opening"
      : t.aria.accuracy > t.atOpen.accuracy
        ? `more often than keeping the priority given at opening (${per100(t.atOpen.accuracy)})`
        : `less often than keeping the priority given at opening (${per100(t.atOpen.accuracy)})`;
  const [field, best] = Object.entries(t.sla.baselines).reduce((a, b) => (b[1] > a[1] ? b : a));
  return `ARIA set the final priority right for ${per100(t.aria.accuracy)} tickets in 100, ${same}. It ranks a ticket that will miss its deadline above one that won't in ${per100(t.sla.auroc)} of 100 pairs (AUROC; 50 is a coin flip), against ${per100(best)} for ${FIELD_NAMES[field] ?? field.replaceAll("_", " ")} alone.`;
}

export function gitlabResult(more: RealData): string {
  const { aria, bm25 } = more.gitlab.service;
  return `For ${count(aria.queries)} of GitLab.com's real incidents, a past incident on the same service was among ARIA's top three ${per100(aria.hit3)} times in 100, and among plain keyword search's ${per100(bm25.hit3)} times.`;
}

export function postmortemsResult(more: RealData): string {
  const { aria, bm25, random } = more.postmortems.cause;
  return `A past post-mortem with the same root cause was among ARIA's top three ${per100(aria.hit3)} times in 100, keyword search's ${per100(bm25.hit3)} and a random pick's ${per100(random.hit3)}.`;
}

// How each simpler method reads inside a sentence.
const METHOD_NAMES: Record<string, string> = {
  model_only: "the calibrated model alone",
  model_with_floors: "the model with its safety floors",
  tfidf_logreg: "a TF-IDF text classifier",
  rules_only: "the rules alone",
  keyword: "keyword matching",
  majority_class: "always answering the commonest level",
};

export function severityResult(data: Evaluation): string {
  const s = data.severity;
  const aria = s.methods.find((m) => m.key === "aria_policy");
  const best = s.methods.find((m) => m.key !== "aria_policy");
  if (!aria || !best) return "";
  return `ARIA rated ${per100(aria.accuracy)} built incidents in 100 at the right level and called ${per100(aria.severeUnderTriage)} in 100 serious ones minor. The most accurate simpler method, ${METHOD_NAMES[best.key] ?? best.label}, rated ${per100(best.accuracy)} in 100 right and called ${per100(best.severeUnderTriage)} in 100 serious ones minor.`;
}

export function decidingResult(data: Evaluation): string {
  const s = data.severity;
  return `ARIA decided ${per100(s.autoDecided)} built incidents in 100 by itself and was right on ${per100(s.accuracyWhenAuto)} in 100 of those. The rest went to a person, and they were the harder ones: its first rating was right on ${per100(s.accuracyWhenFlagged)} in 100 of them.`;
}

export function endToEndResult(data: Evaluation): string {
  const p = data.pipeline;
  const reports = p.valid === 1 ? "Every report" : `${per100(p.valid)} reports in 100`;
  const cause =
    p.leadingCorrect === 1
      ? "in every incident run"
      : `in ${per100(p.leadingCorrect)} of 100 incident runs`;
  return `${reports} passed the citation check, the investigation's leading cause was right ${cause}, and the median report was ready for review after ${p.p50s.toFixed(1)} seconds.`;
}

export function readingResult(data: Evaluation): string {
  const r = data.robustness;
  return `ARIA grouped log lines the way Loghub's hand labels do for ${per100(data.parsing.meanAccuracy)} lines in 100, averaged over ${data.parsing.systems} log formats. It set aside ${per100(r.attackRecall)} in 100 of its own suite's attacks, and ${r.benignFalsePositives ? `${per100(r.benignFalsePositives)} in 100` : "none"} of its harmless but unusual lines.`;
}

export function liveResult(data: Evaluation): string {
  const l = data.live;
  const reports = l.valid === 1 ? "Every report" : `${per100(l.valid)} reports in 100`;
  return `${reports} passed the citation check, and the median report was ready for review after ${l.p50s.toFixed(1)} seconds.`;
}

export function TestQuestions({
  data,
  real,
  more,
}: {
  data: Evaluation;
  real?: RealLogs;
  more: RealData;
}) {
  const target = data.severity.targetCoverage;
  const coverage = [
    {
      name: "Built samples",
      phrase: "built samples",
      detail: "real log lines composed into incidents",
      value: data.severity.coverageWithFloors,
    },
    { name: "BlueGene/L", detail: "a supercomputer's whole log", value: more.bgl.coverage },
    {
      name: "Thunderbird",
      detail: "a second supercomputer's log",
      value: more.thunderbird.coverage,
    },
  ];
  return (
    <div className="grid gap-4">
      <Question
        id="q-unsure"
        question="Does it say when it isn't sure?"
        answer={unsureAnswer(coverage, target)}
      >
        <Coverage rows={coverage} target={target} />
      </Question>
      <Question
        id="q-alarms"
        question="Does it catch serious problems without crying wolf?"
        answer={alarmsAnswer(more.bgl)}
      >
        <AlarmTable bgl={more.bgl} />
        <ul className="grid max-w-prose list-disc gap-2 pl-5 text-sm leading-relaxed">
          {elsewhereLines(real, more).map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </Question>
      <Question
        id="q-memory"
        question="Does it find the right past incident?"
        answer={memoryAnswer(more)}
      >
        <MemoryRows data={data} more={more} />
      </Question>
      <Question
        id="q-limits"
        question="Where does it fall short, and why?"
        answer="Where a system's normal noise looks like trouble, and on logs unlike the ones it was built for."
      >
        <ul className="grid max-w-prose list-disc gap-2 pl-5 text-sm leading-relaxed">
          {shortfallLines(data, more).map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </Question>
    </div>
  );
}
