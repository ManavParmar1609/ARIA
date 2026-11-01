import "server-only";

import demo from "@/data/demo-run.json";
import type { Severity } from "@/lib/api/types";
import { replay, runFacts } from "@/lib/site-data";

// What each slide of the home page's "How it works" carousel shows. Everything comes from the
// recorded run (scripts/record_demo_run.py), so the pictures and the figures under them match
// the example further down the page.

export interface ShowcaseLine {
  lineNo: number;
  text: string;
  /** Logged at WARN or above: the lines that carry the incident. */
  warn: boolean;
  /** The planted line that tries to give ARIA orders; ARIA set it aside. */
  quarantined: boolean;
}

export interface ShowcaseDraft {
  channel: string;
  audience: string;
  title: string;
  body: string;
}

export interface StepShowcase {
  system: string;
  lines: ShowcaseLine[];
  /** The commonest patterns, most lines first. */
  templates: { text: string; count: number; novel: boolean }[];
  severity: Severity;
  probabilities: Record<Severity, number>;
  predictionSet: Severity[];
  setEmpty: boolean;
  claims: { text: string; evidence: string[] }[];
  drafts: ShowcaseDraft[];
  facts: {
    lines: number;
    templates: number;
    pseudonyms: number;
    quarantined: number;
    probability: number;
    similar: number;
    toolCalls: number;
    claims: number;
    coverage: number;
    actions: number;
    reviewSeconds: number;
  };
}

const CHANNEL: Record<string, string> = {
  slack: "Slack message",
  teams: "Teams message",
  webhook: "Update",
  status_page: "Status page",
  ticket_draft: "Ticket draft",
};

const AUDIENCE: Record<string, string> = {
  responders: "for the people on call",
  stakeholders: "for stakeholders",
  customers: "for customers",
};

/** The level ARIA put first in a claim ("SEV3: Moderate: ..."): the severity slide shows it. */
const leadsWithLevel = (text: string) => /^SEV[1-4][:\s(]/.test(text);

export function stepShowcase(): StepShowcase {
  const data = replay();
  const f = runFacts();
  // The log as it arrives: a few routine lines, the first warnings, and the planted line.
  const routine = data.lines.filter((l) => !l.quarantined && l.level !== "WARN").slice(0, 2);
  const warnings = data.lines.filter((l) => l.level === "WARN").slice(0, 2);
  const planted = data.lines.filter((l) => l.quarantined);
  const lines = [...routine, ...warnings, ...planted]
    .sort((a, b) =>
      a.quarantined === b.quarantined ? a.lineNo - b.lineNo : a.quarantined ? 1 : -1,
    )
    .map((l) => ({
      lineNo: l.lineNo,
      text: l.text,
      warn: l.level === "WARN" || l.level === "ERROR" || l.level === "FATAL",
      quarantined: l.quarantined,
    }));
  const templates = [...demo.batch.templates]
    .sort((a, b) => b.count - a.count)
    .slice(0, 3)
    .map((t) => ({ text: t.template, count: t.count, novel: t.novel }));
  // Claims a newcomer can read: not the level (the severity slide has it), and plain words first.
  const claims = data.claims
    .filter((c) => !leadsWithLevel(c.text))
    .sort((a, b) => Number(a.text.includes("<*>")) - Number(b.text.includes("<*>")))
    .slice(0, 2);
  const drafts = demo.actions.map((a) => ({
    channel: CHANNEL[a.kind] ?? "Message",
    audience: AUDIENCE[a.audience] ?? "",
    title: a.title,
    body: a.body,
  }));
  return {
    system: data.system,
    lines,
    templates,
    severity: data.severity,
    probabilities: data.probabilities,
    predictionSet: data.predictionSet,
    setEmpty: data.setEmpty,
    claims,
    drafts,
    facts: {
      lines: f.lines,
      templates: f.templates,
      pseudonyms: f.pseudonyms,
      quarantined: f.quarantined,
      probability: f.probability,
      similar: f.similar,
      toolCalls: f.toolCalls,
      claims: f.claims,
      coverage: f.citationCoverage,
      actions: f.actions,
      reviewSeconds: Math.round(f.timeToReviewMs / 100) / 10,
    },
  };
}
