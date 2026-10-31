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
  const { bgl, hadoop, openstack, tickets, gitlab, injection } = data;
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
      // Against the strong baselines, not the weakest: the highest level and ARIA's own rules.
      compare: `ARIA's rules alone miss ${n(bgl.rules.severeMissed)}, and the highest log level misses ${n(bgl.highestLevel.severeMissed)}. ARIA paged on ${n(bgl.aria.quietPaged)} of ${n(bgl.quiet)} quiet windows; the highest level, on ${n(bgl.highestLevel.quietPaged)}.`,
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
      compare: `A rule on ERROR lines flags ${hadoop.anyError.caught}, and ${hadoop.anyError.falseAlarms} of the ${hadoop.aria.healthy} healthy jobs; ARIA flags ${hadoop.aria.falseAlarms} of them.`,
      caveat: "ARIA has no failure mode for a full disk.",
      anchor: "real-failures-a-hadoop-clusters-jobs",
    },
    {
      key: "openstack",
      name: `${n(openstack.experiments)} OpenStack runs, each with a bug planted`,
      what: `One bug injected into Nova, Cinder or Neutron per run, then a workload of VMs, volumes and networks. ${n(openstack.failed)} runs failed, ${n(openstack.silent)} of them with no API error to say so.`,
      stat: `${n(openstack.paged.caught)} of ${n(openstack.paged.failed)}`,
      statLabel: "Failed runs paged at SEV1-2",
      compare: `It also paged on ${n(openstack.paged.falseAlarms)} of the ${n(openstack.paged.healthy)} runs that did not fail. A rule on ERROR lines flags ${n(openstack.anyError.caught)} failed and ${n(openstack.anyError.falseAlarms)} healthy runs; ranking failed runs above healthy ones, ARIA scores AUROC ${openstack.ranking.aria.value.toFixed(2)} and counting ERROR lines ${openstack.ranking.errors.value.toFixed(2)}, where 0.50 is chance.`,
      caveat: `Unsure of ${n(openstack.unsure)} of the ${n(openstack.experiments)} runs, ARIA sent them to a reviewer: its one OpenStack failure mode is a missing image-cache file.`,
      anchor: "real-failures-bugs-injected-into-openstack",
    },
    {
      key: "tickets",
      name: `${n(tickets.incidents)} ServiceNow tickets`,
      what: `One company's service desk. The ticket model trains on the oldest tickets and is scored on the newest ${n(tickets.test)}.`,
      stat: pct(tickets.aria.accuracy),
      statLabel: "Final priority right",
      compare: `${tickets.aria.accuracy >= tickets.atOpen.accuracy ? "Level with" : "Below"} the priority each ticket opened with. Its SLA risk ranks a breached ticket above one that held its SLA ${pct(tickets.sla.auroc, 0)} of the time (AUROC ${tickets.sla.auroc.toFixed(2)}, where 0.50 is chance), against ${tickets.sla.bestBaseline.toFixed(2)} for the best single field.`,
      caveat:
        tickets.foreseen === 0
          ? `None of the ${tickets.escalated} tickets raised after they opened was foreseen.`
          : `${tickets.foreseen} of the ${tickets.escalated} tickets raised after they opened were foreseen.`,
      anchor: "real-tickets-a-servicenow-service-desk",
    },
    {
      key: "gitlab",
      name: `${n(gitlab.incidents)} GitLab.com incidents`,
      what: `GitLab runs GitLab.com in the open. The incident library holds the ${n(gitlab.memory)} opened before ${gitlab.cutoff.slice(0, 4)}; each of the ${n(gitlab.later)} later ones asks for similar past incidents from its title alone.`,
      stat: pct(memory.aria.hit3),
      statLabel: `Same service among the first ${count(gitlab.top)}`,
      compare: `Past incidents picked at random: ${pct(memory.random.hit3)}. Keyword search alone (BM25): ${pct(memory.bm25.hit3)}.`,
      caveat:
        memory.bm25.hit3 > memory.aria.hit3
          ? "Here keyword search alone did better: the offline embeddings fused in cost recall."
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

// Three across on wide screens, the cards of a short last row widening to fill it; two across on
// tablets, an odd last card spanning both, so no card sits alone in part of a row.
function span(i: number, total: number) {
  const full = total - (total % 3);
  const wide = i < full ? "lg:col-span-2" : total % 3 === 2 ? "lg:col-span-3" : "lg:col-span-6";
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
            // A row subgrid: the names, numbers, comparisons and links of cards side by side line
            // up, however long each card's text runs.
            className={`row-span-5 grid grid-rows-subgrid gap-4 rounded-lg bg-raised p-5 sm:p-7 ${span(i, all.length)}`}
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
              className="self-end justify-self-start text-sm text-foreground underline decoration-control underline-offset-4 hover:decoration-foreground"
            >
              Method and full results<span className="sr-only">: {card.name}</span>
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
