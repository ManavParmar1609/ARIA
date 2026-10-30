import { RollingNumber } from "@/components/aria/rolling-number";
import { count } from "@/lib/format";
import { EVAL_DOC_URL, type RealData } from "@/lib/site-data";

const pct = (x: number, digits = 1) => `${(x * 100).toFixed(digits)}%`;
const n = (x: number) => x.toLocaleString("en");

interface Card {
  key: string;
  name: string;
  what: string;
  stat: string;
  statLabel: string;
  compare: string;
  caveat: string;
  anchor: string;
}

function cards(data: RealData): Card[] {
  const { bgl, hadoop, tickets, gitlab, injection } = data;
  const memory = gitlab.service;
  const failedJobs = hadoop.jobs - (hadoop.byLabel.normal ?? 0);
  const rulesWin = bgl.rules.macroF1 > bgl.aria.macroF1;
  return [
    {
      key: "bgl",
      name: "A supercomputer's whole log",
      what: `${n(bgl.lines)} BlueGene/L lines over ${Math.round(bgl.days)} days, cut into ${n(bgl.windows)} windows and labelled by the administrators' alert tags, which ARIA never sees.`,
      stat: `${n(bgl.aria.severeMissed)} of ${n(bgl.severe)}`,
      statLabel: "Severe windows rated as minor",
      compare: `A keyword rule misses ${n(bgl.keyword.severeMissed)}. ARIA paged on ${n(bgl.aria.quietPaged)} of ${n(bgl.quiet)} quiet windows.`,
      caveat: rulesWin
        ? "Here ARIA's rules alone did better than its rules and model together: the model learned from semi-synthetic windows."
        : "The model learned from semi-synthetic windows, not from this log.",
      anchor: "real-logs-a-supercomputers-alert-tags",
    },
    {
      key: "hadoop",
      name: `${hadoop.jobs} Hadoop jobs, some made to fail`,
      what: `Every container log of ${hadoop.jobs} MapReduce jobs. In ${failedJobs} of them a machine was shut down, the network cut or a disk filled while they ran.`,
      stat: `${hadoop.aria.caught} of ${hadoop.aria.failed}`,
      statLabel: "Failed jobs flagged",
      compare: `A rule on ERROR lines flags ${hadoop.anyError.caught}. ARIA also flagged ${hadoop.aria.falseAlarms} of ${hadoop.aria.healthy} healthy jobs.`,
      caveat: "ARIA has no failure mode for a full disk.",
      anchor: "real-failures-a-hadoop-clusters-jobs",
    },
    {
      key: "tickets",
      name: `${n(tickets.incidents)} ServiceNow tickets`,
      what: `One company's service desk. The ticket model trains on the oldest tickets and is scored on the newest ${n(tickets.test)}.`,
      stat: pct(tickets.aria.accuracy),
      statLabel: "Final priority right",
      compare: `${tickets.aria.accuracy >= tickets.atOpen.accuracy ? "Level with" : "Below"} the priority each ticket opened with. Its SLA risk ranks breaches at AUROC ${tickets.sla.auroc.toFixed(2)}, against ${tickets.sla.bestBaseline.toFixed(2)} for the best single field.`,
      caveat:
        tickets.foreseen === 0
          ? `None of the ${tickets.escalated} tickets raised after they opened was foreseen.`
          : `${tickets.foreseen} of the ${tickets.escalated} tickets raised after they opened were foreseen.`,
      anchor: "real-tickets-a-servicenow-service-desk",
    },
    {
      key: "gitlab",
      name: `${n(gitlab.incidents)} GitLab.com incidents`,
      what: `GitLab runs GitLab.com in the open. Incident memory holds the ${n(gitlab.memory)} opened before ${gitlab.cutoff.slice(0, 4)}; each of the ${n(gitlab.later)} later ones asks for similar past incidents from its title alone.`,
      stat: pct(memory.aria.hit3),
      statLabel: `Same service among the first ${count(gitlab.top)}`,
      compare: `Past incidents picked at random: ${pct(memory.random.hit3)}. BM25 alone: ${pct(memory.bm25.hit3)}.`,
      caveat:
        memory.bm25.hit3 > memory.aria.hit3
          ? "Here BM25 alone did better: the offline embeddings fused in cost recall."
          : "The embeddings are the offline ones, fitted on these incidents' own words.",
      anchor: "real-incidents-similar-past-incidents",
    },
    {
      key: "injection",
      name: `${n(injection.attacks)} prompt-injection attacks`,
      what: `From ${count(injection.sources.length)} public benchmarks the detector was never tuned on, each hidden in a log line.`,
      stat: pct(injection.rate),
      statLabel: "Caught by the detector",
      compare: `It flagged ${pct(injection.benign.rate)} of benign look-alikes and ${injection.realFlagged === 0 ? "none" : n(injection.realFlagged)} of ${n(injection.realLines)} real log lines.`,
      caveat: "Fencing, the prediction set and approval do not rely on it.",
      anchor: "prompt-injection-public-benchmarks",
    },
  ];
}

// Three across and then two on wide screens; two across on tablets, an odd last card spanning
// both, so no card sits alone in half a row.
function span(i: number, total: number) {
  const wide = i < 3 ? "lg:col-span-2" : "lg:col-span-3";
  return total % 2 === 1 && i === total - 1 ? `md:col-span-2 ${wide}` : wide;
}

/** More real datasets, each with the headline beside its baseline and its caveat. */
export function RealDatasets({ data }: { data: RealData }) {
  const all = cards(data);
  return (
    <div className="grid gap-8">
      <div className="grid max-w-3xl gap-3">
        <h3 className="text-2xl leading-tight tracking-heading sm:text-3xl">
          And on {count(all.length)} more real datasets
        </h3>
        <p className="text-muted-foreground">
          Each with labels its owners gave it, and each scored against a simple baseline. Some of
          the results are good, some are not; all of them come from the same <code>make eval</code>.
        </p>
      </div>
      <ul className="grid gap-4 md:grid-cols-2 lg:grid-cols-6">
        {all.map((card, i) => (
          <li
            key={card.key}
            className={`grid content-start gap-4 rounded-lg bg-raised p-5 sm:p-7 ${span(i, all.length)}`}
          >
            <div className="grid gap-1.5">
              <h4 className="text-lg leading-snug tracking-heading">{card.name}</h4>
              <p className="text-sm text-muted-foreground">{card.what}</p>
            </div>
            <dl className="grid gap-1">
              <dt className="order-2 text-sm text-foreground">{card.statLabel}</dt>
              <dd className="stat order-1 text-[2.25rem] sm:text-[2.75rem]">
                <RollingNumber value={card.stat} />
              </dd>
            </dl>
            <p className="text-sm">{card.compare}</p>
            <p className="text-sm text-faint">{card.caveat}</p>
            <a
              href={`${EVAL_DOC_URL}#${card.anchor}`}
              className="justify-self-start text-sm text-foreground underline decoration-control underline-offset-4 hover:decoration-foreground"
            >
              Method and full results<span className="sr-only">: {card.name}</span>
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
