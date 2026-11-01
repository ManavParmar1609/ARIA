import { Fragment, type ReactNode } from "react";

import { Term } from "@/components/aria/term";
import {
  ALERT_METHODS,
  ALERT_SCORES,
  cell,
  DOMAIN_CARDS,
  domainAspects,
  domainSummary,
  faultName,
  PRIORITY_METHODS,
  rankCell,
  serviceSystem,
  stepName,
  writeUpAnchor,
  type Aspect,
} from "@/components/console/domain-results";
import { Facts, MethodTable, pct, Section } from "@/components/console/eval-parts";
import type {
  Anomalies,
  Chance,
  DomainResult,
  FaultWindows,
  IssuePriority,
  KubernetesIncidents,
  Naming,
  NewDomains,
  SecurityAlerts,
} from "@/lib/domains";
import { capitalise, count as words } from "@/lib/format";
import { EVAL_DOC_URL } from "@/lib/site-data";
import type { TuningRecord } from "@/lib/tuning";

// The tests on data from fields ARIA was never built for (ring C, lib/domains.ts), as cards under
// "Tests on real data". Every number comes from the results, and every judging word from
// domain-results.ts.

const n = (x: number) => x.toLocaleString("en");
const per100 = (x: number) => Math.round(x * 100);
const list = (items: string[]) =>
  new Intl.ListFormat("en-GB", { type: "conjunction" }).format(items);

/** "A, B and C" for any nodes, such as words with their definitions. */
function joined(nodes: ReactNode[]): ReactNode {
  return nodes.map((node, i) => (
    <Fragment key={i}>
      {i === 0 ? null : i === nodes.length - 1 ? " and " : ", "}
      {node}
    </Fragment>
  ));
}

/** What every card shares: its title, verdict, result, shortfall, figures, badge and link. */
function card(d: DomainResult, tuning: TuningRecord | null | undefined) {
  const { id, title, heading } = DOMAIN_CARDS[d.key];
  const summary = domainSummary(d);
  return {
    facts: summary.facts,
    section: {
      id,
      title,
      level: 4 as const,
      tuning: tuning?.[`domains.${d.key}`],
      verdict: summary.verdict,
      headline: summary.result,
      shortfall: summary.shortfall,
      source: d.citation,
      link: `${EVAL_DOC_URL}${writeUpAnchor(heading)}`,
    },
  };
}

/** The naming table's rows: each method's first suspect and first three, and a random pick's. */
function namingRows(methods: [string, Naming][], random: Chance) {
  return [
    ...methods.map(([name, naming], i) => ({
      name,
      cells: [cell(naming.first), cell(naming.firstThree)],
      strong: i === 0,
    })),
    {
      name: "A service at random (expected)",
      cells: [`${per100(random.first)}%`, `${per100(random.firstThree)}%`],
    },
  ];
}

function NamingTable({ label, rows }: { label: string; rows: ReturnType<typeof namingRows> }) {
  return (
    <MethodTable
      label={label}
      head={["Method", "First suspect", "Among the first three"]}
      rows={rows}
    />
  );
}

function AlertsCard({ s, tuning }: { s: SecurityAlerts; tuning?: TuningRecord | null }) {
  const { section, facts } = card(s, tuning);
  const per = s.perNetwork;
  // Harmful steps first, the way the shortfall reads them.
  const steps = [...s.steps].sort((a, b) => Number(b.harmful) - Number(a.harmful));
  return (
    <Section
      {...section}
      what={
        <>
          Alerts that intrusion detectors raised on {words(s.networks)} simulated company networks,
          each attacked once in several steps amid everyday noise. Can ARIA{" "}
          <Term name="auroc" instance={section.id}>
            rank
          </Term>{" "}
          the stretches of an attack above routine ones, and does it{" "}
          <Term name="paged" instance={section.id}>
            page
          </Term>{" "}
          on the steps that do harm?
        </>
      }
      intro={
        <>
          {n(s.alerts)} alerts, cut into {n(s.windows)} stretches of {s.windowMin} minutes:{" "}
          {n(s.attackWindows)} overlap a step of the attack, and {n(s.routineWindows)} hold only
          routine alerts, most of them false alarms set off by ordinary users. ARIA rates each
          stretch from its alert lines alone, remembering the routine alerts of the network&apos;s
          earlier stretches as a deployment would. A stretch counts as flagged at SEV1 to SEV3 and
          paged at SEV1 or SEV2. The data marks the attacks, not their severity.
        </>
      }
    >
      <Facts items={facts} />
      <MethodTable
        label="How well each score ranks attack stretches above routine ones (AUROC)"
        head={["Score", "AUROC (95% interval; 0.5 is a coin flip)"]}
        rows={s.rankings.map(({ key, ranking }) => ({
          name: ALERT_SCORES[key] ?? key,
          cells: [rankCell(ranking)],
          strong: key === "aria_probability",
        }))}
      />
      {per ? (
        <p className="max-w-prose text-sm text-muted-foreground">
          Network by network, the median AUROC of ARIA&apos;s score was {per.median.toFixed(3)} and
          the worst {per.worst.toFixed(3)}; on{" "}
          {per.belowChance === 0 ? "none" : words(per.belowChance)} of the {words(s.networks)}{" "}
          networks did it rank attack stretches below routine ones.
        </p>
      ) : null}
      <MethodTable
        label="Attack and routine stretches flagged and paged, by method"
        head={["Method", "Attack, flagged", "Attack, paged", "Routine, flagged", "Routine, paged"]}
        rows={s.methods.map((m) => ({
          name: ALERT_METHODS[m.key] ?? m.key,
          cells: [
            cell(m.attackFlagged),
            cell(m.attackPaged),
            cell(m.routineFlagged),
            cell(m.routinePaged),
          ],
          strong: m.key === "aria",
        }))}
      />
      <MethodTable
        label="Each kind of attack step, as ARIA flagged and paged it"
        head={["Attack step", "Does harm", "Times", "Flagged", "Paged"]}
        rows={steps.map((t) => ({
          name: stepName(t.key),
          cells: [t.harmful ? "Yes" : "No", n(t.occurrences), n(t.flagged), n(t.paged)],
        }))}
      />
    </Section>
  );
}

function FaultCard({ s, tuning }: { s: FaultWindows; tuning?: TuningRecord | null }) {
  const { section, facts } = card(s, tuning);
  const systems = list(s.systems.map((system) => serviceSystem(system.key)));
  const span = s.windowMin === 1 ? "minute" : s.windowMin ? `${s.windowMin} minutes` : null;
  const kinds = s.key === "nezha" ? s.faults.map((f) => faultName(f.key)) : [];
  const shops = s.systems.flatMap((system) =>
    system.detail ? [{ ...system, ...system.detail }] : [],
  );
  const { aria } = s;
  return (
    <Section
      {...section}
      what={
        <>
          {s.key === "nezha"
            ? `${n(s.cases)} faults${kinds.length ? ` of ${words(kinds.length)} kinds (${list(kinds)})` : ""}, injected one at a time into the pods of ${systems}, a demo online shop on Kubernetes${s.days ? `, over ${words(s.days)} days` : ""}.`
            : `${n(s.cases)} faults put into the code of one service at a time in ${systems}, demo shops built from many small services.`}{" "}
          Does ARIA flag the logs after a fault, leave the logs before it alone, and{" "}
          <Term name="service-at-fault" instance={section.id}>
            name the service at fault
          </Term>
          ?
        </>
      }
      intro={
        <>
          Each fault gives two stretches of logs:{" "}
          {span
            ? `the service logs of the ${span} before it, which are healthy, and of the ${span} from it on`
            : "every service's logs from before it, which are healthy, and from it on"}
          . Each stretch is triaged offline, end to end, and counts as flagged at SEV1 to SEV3 and
          paged at SEV1 or SEV2. {n(s.overCap)} of the {n(s.windows)} stretches hold more lines than
          one run reads ({n(s.lineCap)}), so ARIA reads up to that. The data marks the faults, not
          their severity.
        </>
      }
    >
      <Facts items={facts} />
      <MethodTable
        label="Faulty and healthy stretches flagged, by method"
        head={["Method", "Faulty stretches flagged", "Healthy stretches flagged"]}
        rows={[
          {
            name: "ARIA, end to end",
            cells: [cell(aria.faulty), cell(aria.healthy)],
            strong: true,
          },
          {
            name: "ARIA, paged only (SEV1-2)",
            cells: [cell(aria.pagedFaulty), cell(aria.pagedHealthy)],
          },
          { name: "Any error line", cells: [cell(s.anyError.faulty), cell(s.anyError.healthy)] },
        ]}
      />
      <MethodTable
        label="How well each score ranks faulty stretches above healthy ones (AUROC)"
        head={["Score", "AUROC (95% interval; 0.5 is a coin flip)"]}
        rows={[
          { name: "ARIA's probability of SEV1-2", cells: [rankCell(aria.ranking)], strong: true },
          { name: "Error lines, counted", cells: [rankCell(s.errorRanking)] },
        ]}
      />
      <p className="max-w-prose text-sm text-muted-foreground">
        Case by case, ARIA rated the faulty stretch above the healthy one before it in{" "}
        {n(aria.paired.higher)}, level with it in {n(aria.paired.same)} and below it in{" "}
        {n(aria.paired.lower)}.
      </p>
      <NamingTable
        label="How often each method names the service at fault"
        rows={namingRows(
          [
            ["ARIA", aria.naming],
            ["Most error lines", s.mostErrors],
            ...(s.mostChanged
              ? [
                  [
                    "Largest change in a service's share of the lines (reads both stretches)",
                    s.mostChanged,
                  ] as [string, Naming],
                ]
              : []),
          ],
          s.random,
        )}
      />
      {shops.length > 1 ? (
        <MethodTable
          label="Each shop"
          head={["Shop", "Cases", "Faulty flagged", "Healthy flagged", "Named in the first three"]}
          rows={shops.map((shop) => ({
            name: serviceSystem(shop.key),
            cells: [
              n(shop.cases),
              cell(shop.faulty),
              cell(shop.healthy),
              cell(shop.naming.firstThree),
            ],
          }))}
        />
      ) : null}
      {kinds.length ? (
        <MethodTable
          label="Each kind of fault"
          head={["Fault", "Cases", "Flagged"]}
          rows={s.faults.map((f) => ({
            name: capitalise(faultName(f.key)),
            cells: [n(f.cases), cell(f.flagged)],
          }))}
        />
      ) : null}
    </Section>
  );
}

function AnomaliesCard({ s, tuning }: { s: Anomalies; tuning?: TuningRecord | null }) {
  const { section, facts } = card(s, tuning);
  const systems = list(s.systems.map((system) => serviceSystem(system.key)));
  const levels = s.levels.map((l) => l.key);
  return (
    <Section
      {...section}
      what={
        <>
          {n(s.anomalous)} anomalies injected into {systems}, demo systems built from many small
          services{levels.length ? `, at ${words(levels.length)} levels (${list(levels)})` : ""},
          plus {words(s.normal)} normal runs. Does ARIA flag the anomalous runs, leave the normal
          ones alone, and{" "}
          <Term name="service-at-fault" instance={section.id}>
            name the service
          </Term>{" "}
          each anomaly targets?
        </>
      }
      intro={
        <>
          Each run&apos;s newest log lines, up to the {n(s.lineCap)} one run reads, are triaged
          offline, end to end. A run counts as flagged at SEV1 to SEV3 and paged at SEV1 or SEV2.
          The data marks the anomalies, not their severity, and its {words(s.normal)} normal runs
          are too few to measure false alarms.
        </>
      }
    >
      <Facts items={facts} />
      <MethodTable
        label="Anomalous and normal runs flagged, by method"
        head={["Method", "Anomalous runs flagged", "Normal runs flagged"]}
        rows={[
          {
            name: "ARIA, end to end",
            cells: [cell(s.flagged), `${n(s.normalFlagged)} of ${n(s.normal)}`],
            strong: true,
          },
          {
            name: "Any error line",
            cells: [cell(s.anyError.flagged), `${n(s.anyError.normalFlagged)} of ${n(s.normal)}`],
          },
        ]}
      />
      <MethodTable
        label="ARIA's level for the anomalies at each level"
        head={["Level", "Runs", "Flagged", "SEV1", "SEV2", "SEV3", "SEV4"]}
        rows={s.levels.map((l) => ({
          name: capitalise(l.key),
          cells: [
            n(l.runs),
            cell(l.flagged),
            ...["SEV1", "SEV2", "SEV3", "SEV4"].map((sev) => n(l.severity[sev] ?? 0)),
          ],
        }))}
      />
      <NamingTable
        label="How often each method names the targeted service"
        rows={namingRows(
          [
            ["ARIA", s.naming],
            ["Most error lines", s.mostErrors],
          ],
          s.random,
        )}
      />
    </Section>
  );
}

function KubernetesCard({ s, tuning }: { s: KubernetesIncidents; tuning?: TuningRecord | null }) {
  const { section, facts } = card(s, tuning);
  const skipped = s.found - s.scenarios;
  return (
    <Section
      {...section}
      what={
        <>
          {n(s.scenarios)} incidents on a Kubernetes cluster running a demo shop, each caused by one
          injected fault. ARIA reads what the person on call gets: the alerts firing and the{" "}
          {s.windowMin} minutes of events and logs before the incident. Does it{" "}
          <Term name="paged" instance={section.id}>
            page
          </Term>{" "}
          on them, and{" "}
          <Term name="service-at-fault" instance={section.id}>
            name the service at fault
          </Term>
          ?
        </>
      }
      intro={
        <>
          Each incident is triaged offline, end to end, and counts as flagged at SEV1 to SEV3 and
          paged at SEV1 or SEV2. Every scenario is an incident, so this test cannot show false
          alarms; the healthy stretches of the microservice tests do.{" "}
          {skipped > 0
            ? `${capitalise(words(skipped))} ${skipped === 1 ? "scenario has" : "scenarios have"} no incident time, as the alerts never fired, and ${skipped === 1 ? "is" : "are"} left out. `
            : ""}
          The service at fault is a workload marked as the root cause or, when the root cause is not
          a workload (a setting, a quota, an autoscaler), the first workloads it spreads to;{" "}
          {n(s.withService)} incidents have one.
        </>
      }
    >
      <Facts items={facts} />
      <MethodTable
        label="Incidents flagged and paged, by method"
        head={["Method", "Incidents flagged", "Incidents paged"]}
        rows={[
          { name: "ARIA, end to end", cells: [cell(s.flagged), cell(s.paged)], strong: true },
          {
            name: "The alerts' own severity",
            cells: [cell(s.alerts.flagged), cell(s.alerts.paged)],
          },
        ]}
      />
      {s.anyError ? (
        <p className="max-w-prose text-sm text-muted-foreground">
          An alert on any error line would have flagged {n(s.anyError.hits)} of the{" "}
          {n(s.anyError.of)} incidents.
        </p>
      ) : null}
      <NamingTable
        label="How often each method names the service at fault"
        rows={namingRows(
          [
            ["ARIA", s.naming],
            ["The services the alerts name", s.alertedServices],
            ["Most error lines", s.mostErrors],
          ],
          s.random,
        )}
      />
    </Section>
  );
}

// Whose Jira each tracker is, as the data keys them.
const TRACKERS: Record<string, string> = { Apache: "Apache's", Jira: "Atlassian's" };

function PriorityCard({ s, tuning }: { s: IssuePriority; tuning?: TuningRecord | null }) {
  const { section, facts } = card(s, tuning);
  const owners = list(s.trackers.map((t) => TRACKERS[t.key] ?? t.key));
  const changed = s.pooled.changedAfterOpen;
  return (
    <Section
      {...section}
      what={`${n(s.testTickets)} recent issues from ${owners} public Jira trackers, each with the priority people gave it. ARIA's ticket model learned from one company's service desk: can it set another organisation's priorities?`}
      intro={
        <>
          ARIA&apos;s ticket model reads what a ticket has when it opens: here, the issue&apos;s
          type, first component, project and open time. Jira has no impact or urgency, so the model
          alone decides each priority. The {n(s.testTickets)} newest issues are scored; the{" "}
          {n(s.referenceTickets)} older ones set the simple methods&apos; levels. Urgent means
          levels 1 and 2 (Blocker and Critical, or Highest and High). The priority of{" "}
          {n(changed.hits)} of the {n(changed.of)} issues changed after they opened (
          {per100(changed.share)}%); ARIA&apos;s model never sees the opening priority.
        </>
      }
    >
      <Facts items={facts} />
      {s.trackers.map((t) => (
        <div key={t.key} className="grid gap-2">
          <p className="text-sm font-medium text-foreground">
            {capitalise(TRACKERS[t.key] ?? t.key)} Jira, {n(t.tickets)} issues
          </p>
          <MethodTable
            label={`${capitalise(TRACKERS[t.key] ?? t.key)} Jira: priority by method`}
            head={[
              "Method",
              "Right priority (accuracy)",
              "Balance (macro-F1)",
              "Urgent rated 3 or 4",
            ]}
            rows={t.methods.map((m) => ({
              name: PRIORITY_METHODS[m.key] ?? m.key,
              cells: [pct(m.accuracy), m.macroF1.toFixed(3), cell(m.urgentMissed)],
              strong: m.key === "aria",
            }))}
          />
        </div>
      ))}
    </Section>
  );
}

function DomainCard({ d, tuning }: { d: DomainResult; tuning?: TuningRecord | null }) {
  switch (d.key) {
    case "ait-ads":
      return <AlertsCard s={d} tuning={tuning} />;
    case "rcaeval":
    case "nezha":
      return <FaultCard s={d} tuning={tuning} />;
    case "anomod":
      return <AnomaliesCard s={d} tuning={tuning} />;
    case "itbench":
      return <KubernetesCard s={d} tuning={tuning} />;
    case "jira":
      return <PriorityCard s={d} tuning={tuning} />;
  }
}

// What the tests measure between them, with the words a newcomer may not know defined.
const ASPECT_WORDS: Record<Aspect, ReactNode> = {
  notice: "notices a problem",
  rank: (
    <>
      <Term name="auroc" instance="ev-domains">
        ranks
      </Term>{" "}
      it above routine noise
    </>
  ),
  name: (
    <Term name="service-at-fault" instance="ev-domains">
      names the service at fault
    </Term>
  ),
  priority: "sets a ticket's priority",
};

/**
 * The tests on new kinds of data, as a group under "Tests on real data": what they measure, one
 * card for each suite with results, and a line naming the suites not run yet.
 */
export function NewDomainCards({
  domains,
  tuning,
}: {
  domains: NewDomains;
  tuning?: TuningRecord | null;
}) {
  const { results, notRun } = domains;
  const one = results.length === 1;
  return (
    <section aria-labelledby="ev-domains" className="grid gap-4 pt-6">
      <div className="grid max-w-3xl gap-2">
        <h3 id="ev-domains" className="scroll-mt-24 text-2xl leading-snug lg:scroll-mt-8">
          New kinds of data
        </h3>
        {results.length ? (
          <p className="max-w-prose text-base text-muted-foreground">
            {capitalise(words(results.length))} public, labelled{" "}
            {one ? "dataset from a field" : "datasets from fields"} ARIA was never built for.{" "}
            {one ? "It does not label" : "None of them labels"} severity, so instead{" "}
            {one ? "it tests" : "they test"} whether ARIA{" "}
            {joined(domainAspects(results).map((aspect) => ASPECT_WORDS[aspect]))}. Every figure
            comes with its{" "}
            <Term name="interval" instance="ev-domains">
              95% interval
            </Term>
            .
          </p>
        ) : null}
        {notRun.length ? (
          <p className="max-w-prose text-sm text-muted-foreground">
            Not run yet: {list(notRun.map((key) => DOMAIN_CARDS[key].label))}. Their data was not
            downloaded when these results were made.
          </p>
        ) : null}
      </div>
      {results.map((d) => (
        <DomainCard key={d.key} d={d} tuning={tuning} />
      ))}
    </section>
  );
}
