"use client";

import {
  BookOpenTextIcon,
  CircleCheckIcon,
  CircleDotIcon,
  CircleIcon,
  FileTextIcon,
  GaugeIcon,
  ScanSearchIcon,
  SearchCheckIcon,
  UserRoundCheckIcon,
  type LucideIcon,
} from "lucide-react";
import { useMemo, type ReactNode } from "react";

import type { Hypothesis, RunEvent, RunStateValues, SeverityAssessment } from "@/lib/api/types";
import { listed, writtenOffline } from "@/lib/format";
import { cn } from "@/lib/utils";

import { Citations } from "./evidence";

type Tone = "slate" | "keylime" | "mint" | "sage" | "cream" | "raised";
type TurnState = "waiting" | "working" | "done" | "yours";

interface Turn {
  id: string;
  name: string;
  job: string;
  icon: LucideIcon;
  tone: Tone;
  nodes: string[];
  said: ReactNode[];
}

// Each agent keeps one panel tint for its avatar. The tint is decoration only: the words beside it
// say what happened.
const TONE: Record<Tone, string> = {
  slate: "bg-panel-slate",
  keylime: "bg-panel-keylime",
  mint: "bg-panel-mint",
  sage: "bg-panel-sage",
  cream: "bg-raised ring-1 ring-rule ring-inset",
  raised: "bg-sunken",
};

const STATUS_WORD: Record<Hypothesis["status"], string> = {
  supported: "Supported",
  refuted: "Ruled out",
  inconclusive: "Not settled",
  open: "Still open",
};

const n = (value: number) => value.toLocaleString("en");
const pct = (p: number | undefined) => `${Math.round(100 * (p ?? 0))}%`;

// Parallel shards run one node several times at once, and a resumed review starts its node
// again, so each node counts the runs still going rather than starts against finishes.
function progress(events: RunEvent[], nodes: string[]) {
  let started = false;
  let paused = false;
  const running: Record<string, number> = {};
  const settle = (node: string) => {
    running[node] = Math.max(0, (running[node] ?? 0) - 1);
  };
  for (const e of events) {
    const node = e.node ?? "";
    if (!nodes.includes(node)) continue;
    if (e.kind === "node_started") {
      started = true;
      paused = false; // a review resumes by starting its node again
      running[node] = (running[node] ?? 0) + 1;
    } else if (e.kind === "node_finished") {
      settle(node);
    } else if (e.kind === "interrupt") {
      paused = true; // the node stops here until a person answers
      settle(node);
    }
  }
  const working = Object.values(running).some((count) => count > 0);
  return { started, working, paused };
}

function severityLine(sev: SeverityAssessment): ReactNode[] {
  const probs = sev.probabilities ?? {};
  const top = (Object.entries(probs) as [string, number][]).sort((a, b) => b[1] - a[1])[0];
  const floorHit = sev.rule_hits.find((h) => h.effect === "floor" && h.severity === sev.floor);
  const lines: ReactNode[] = [];
  if (sev.decided_by === "rules" && floorHit) {
    lines.push(
      <>
        Rated it {sev.severity}. A safety floor holds it at {sev.floor} or above: &ldquo;
        {floorHit.title}&rdquo;. <Citations ids={floorHit.evidence_ids} />
      </>,
    );
    if (top && top[0] !== sev.severity) {
      lines.push(
        `On its own, the calibrated model put ${pct(top[1])} on ${top[0]}: the floor is there for exactly this.`,
      );
    }
  } else if (sev.decided_by === "model") {
    lines.push(
      `Rated it ${sev.severity}: the calibrated model was sure (${pct(probs[sev.severity])}).`,
    );
  } else if (sev.decided_by === "llm") {
    lines.push(
      `Rated it ${sev.severity}: a model chose it from the prediction set {${sev.prediction_set.join(", ")}}.`,
    );
  } else if (sev.decided_by === "fallback") {
    lines.push(
      sev.set_empty
        ? `Rated it ${sev.severity}: no severity was likely enough on its own, so it took the most likely and flagged it for you.`
        : sev.prediction_set.length === 1
          ? `Rated it ${sev.severity}: only ${sev.severity} remained, but not with enough confidence to decide alone, so it flagged it for you.`
          : `Rated it ${sev.severity}: unsure between ${listed(sev.prediction_set)}, so it took the most severe and flagged it for you.`,
    );
  } else {
    lines.push(`Rated it ${sev.severity} by its rules (${sev.decided_by}).`);
  }
  return lines;
}

/** The run told as its agents' turns: who did what, what they concluded, and why. */
export function AgentTeam({ values, events }: { values: RunStateValues; events: RunEvent[] }) {
  const turns = useMemo<Turn[]>(() => {
    const batch = values.batch;
    const flows = batch?.flows;
    const sev = values.severity;
    const retrieval = values.retrieval;
    const inv = values.investigation;
    const report = values.report;
    const actions = values.actions ?? [];
    const review = values.review;

    const parser: ReactNode[] = [];
    if (batch) {
      const f = batch.features;
      parser.push(
        `Read ${n(batch.n_raw_lines)} lines${batch.shards > 1 ? `, split across ${batch.shards} parsers working at once,` : ""} and found ${n(f.n_templates)} message patterns.`,
      );
      const redacted = Object.values(batch.guard.redactions?.counts ?? {}).reduce(
        (a, b) => a + b,
        0,
      );
      if (redacted) parser.push(`Redacted or pseudonymised ${n(redacted)} secrets and addresses.`);
      if (batch.guard.injections?.length) {
        parser.push(
          `Quarantined ${n(batch.guard.injections.length)} ${batch.guard.injections.length === 1 ? "line that reads" : "lines that read"} like prompt injection.`,
        );
      }
      const kind = flows?.examples[0]?.kind ?? Object.keys(flows?.checked ?? {})[0];
      const checked = kind ? (flows?.checked[kind] ?? 0) : 0;
      if (flows && kind && flows.broken) {
        parser.push(
          <>
            Followed {n(checked)} {kind}s from start to finish: {n(flows.broken)} never finished
            every step, with no error to say so.{" "}
            {flows.evidence_id ? <Citations ids={[flows.evidence_id]} /> : null}
          </>,
        );
      } else if (kind && checked) {
        parser.push(`Followed ${n(checked)} ${kind}s from start to finish: each one finished.`);
      }
      if (f.error_events) {
        parser.push(
          `${n(f.error_events)} error ${f.error_events === 1 ? "line" : "lines"}, on ${n(f.error_nodes)} ${f.error_nodes === 1 ? "server" : "servers"}.`,
        );
      }
    }

    const memory: ReactNode[] = [];
    if (retrieval) {
      const best = retrieval.incidents[0];
      if (best) {
        memory.push(
          <>
            Recalled {retrieval.incidents.length} similar past incident
            {retrieval.incidents.length === 1 ? "" : "s"}. The closest: &ldquo;{best.title}&rdquo; (
            {best.severity}). {best.evidence_id ? <Citations ids={[best.evidence_id]} /> : null}
          </>,
        );
      } else {
        memory.push("Found no similar past incident in memory.");
      }
      if (retrieval.runbooks.length) {
        memory.push(`Pulled runbooks: ${retrieval.runbooks.map((r) => r.slug).join(", ")}.`);
      }
    }

    const investigator: ReactNode[] = [];
    if (inv) {
      const calls = inv.tool_calls?.length ?? 0;
      if (inv.hypotheses.length) {
        investigator.push(
          `Tested ${inv.hypotheses.length} possible cause${inv.hypotheses.length === 1 ? "" : "s"} with ${calls} read-only tool call${calls === 1 ? "" : "s"}.`,
        );
        for (const h of inv.hypotheses) {
          investigator.push(
            <span className="grid gap-0.5">
              <span>
                <span
                  className={cn(
                    "mr-2 inline-block rounded-xs border px-1.5 text-xs",
                    h.status === "supported"
                      ? "border-primary bg-highlight font-medium text-highlight-foreground"
                      : "border-rule text-muted-foreground",
                  )}
                >
                  {STATUS_WORD[h.status]}
                  {h.status === "supported" ? `, ${pct(h.confidence)}` : ""}
                </span>
                {h.statement} <Citations ids={[...h.supporting, ...h.refuting].slice(0, 4)} />
              </span>
            </span>,
          );
        }
      } else if (inv.stopped_reason === "disabled") {
        investigator.push("Not asked to investigate on this run.");
      } else {
        investigator.push("Found no cause worth testing.");
      }
      const replans = values.plan?.replans ?? 0;
      if (replans) {
        investigator.push(
          `The evidence looked thin, so the planner sent the run back for ${replans === 1 ? "another round" : `${replans} more rounds`}.`,
        );
      }
    }

    const reporter: ReactNode[] = [];
    if (report) {
      const v = report.validation;
      reporter.push(
        `Wrote the report${writtenOffline(report) ? " from the evidence alone, with no model" : " with a model"}: ${n(v?.checked_claims ?? 0)} claims, ${pct(v?.citation_coverage)} of them citing evidence.`,
      );
      reporter.push(
        v?.ok
          ? "The validator checked every claim against what it cites: passed."
          : `The validator found ${v?.issues?.length ?? 0} issue(s) to fix before publishing.`,
      );
      if (actions.length) {
        reporter.push(
          `Drafted ${actions.length} message${actions.length === 1 ? "" : "s"}; none is sent until a person approves.`,
        );
      }
    }

    const you: ReactNode[] = [];
    if (review) {
      you.push(
        `${review.decision === "approve" ? "Approved" : review.decision === "reject" ? "Discarded" : "Edited and approved"} by ${review.reviewer && review.reviewer !== "anonymous" ? review.reviewer : "a reviewer"}.`,
      );
    } else if (report) {
      you.push(
        "Waiting for you: approve, edit before sending, or discard the draft. Nothing has been sent.",
      );
    }

    return [
      {
        id: "parser",
        name: "Parser",
        job: "Reads every line, hides secrets, follows each unit of work",
        icon: ScanSearchIcon,
        tone: "slate",
        nodes: ["plan", "parse_shard", "merge"],
        said: parser,
      },
      {
        id: "severity",
        name: "Severity",
        job: "Rules, a calibrated model and a prediction set",
        icon: GaugeIcon,
        tone: "keylime",
        nodes: ["severity"],
        said: sev ? severityLine(sev) : [],
      },
      {
        id: "memory",
        name: "Memory",
        job: "Recalls similar incidents and their runbooks",
        icon: BookOpenTextIcon,
        tone: "mint",
        nodes: ["recall", "widen"],
        said: memory,
      },
      {
        id: "investigator",
        name: "Investigator",
        job: "Tests causes with read-only tools",
        icon: SearchCheckIcon,
        tone: "sage",
        nodes: ["investigate", "assess"],
        said: investigator,
      },
      {
        id: "reporter",
        name: "Reporter and critic",
        job: "Writes the cited report, then checks it",
        icon: FileTextIcon,
        tone: "cream",
        nodes: ["report", "comms"],
        said: reporter,
      },
      {
        id: "you",
        name: "You",
        job: "Nothing is published or sent without a person",
        icon: UserRoundCheckIcon,
        tone: "raised",
        nodes: ["review", "publish", "reject"],
        said: you,
      },
    ];
  }, [values]);

  return (
    // Lines quote names from the logs (Java classes, block IDs) that can be wider than a phone.
    <ol aria-label="How the agents worked" className="grid wrap-anywhere">
      {turns.map((turn, i) => {
        const p = progress(events, turn.nodes);
        const state: TurnState = p.paused
          ? "yours"
          : p.started && !p.working
            ? "done"
            : p.started
              ? "working"
              : "waiting";
        const Icon = turn.icon;
        return (
          <li key={turn.id} className="grid grid-cols-[2.75rem_1fr] gap-x-4">
            <div className="flex flex-col items-center">
              <span
                aria-hidden
                className={cn(
                  "grid size-11 shrink-0 place-items-center rounded-full text-heading",
                  TONE[turn.tone],
                  state === "waiting" && "opacity-50",
                )}
              >
                <Icon className="size-5" />
              </span>
              {i < turns.length - 1 ? <span aria-hidden className="w-px flex-1 bg-rule" /> : null}
            </div>
            <div className={cn("grid min-w-0 gap-2 pb-8", i === turns.length - 1 && "pb-0")}>
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <h3 className="font-sans text-base font-semibold">
                  {turn.name}
                  <span className="ml-2 text-sm font-normal text-muted-foreground">{turn.job}</span>
                </h3>
                <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  {state === "done" ? (
                    <CircleCheckIcon aria-hidden className="size-3.5 text-ok" />
                  ) : state === "working" ? (
                    <CircleDotIcon
                      aria-hidden
                      className="size-3.5 animate-pulse motion-reduce:animate-none"
                    />
                  ) : state === "yours" ? (
                    <UserRoundCheckIcon aria-hidden className="size-3.5" />
                  ) : (
                    <CircleIcon aria-hidden className="size-3.5" />
                  )}
                  {state === "done"
                    ? "Done"
                    : state === "working"
                      ? "Working"
                      : state === "yours"
                        ? "Your turn"
                        : "Not yet"}
                </span>
              </div>
              {turn.said.length ? (
                <ul className="grid gap-1.5 text-sm">
                  {turn.said.map((line, j) => (
                    <li key={j} className="text-pretty">
                      {line}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
