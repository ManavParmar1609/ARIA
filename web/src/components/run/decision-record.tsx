"use client";

import { ErrorState, LoadingRows } from "@/components/console/states";
import { useRunRecord, type DecisionRecordEntry } from "@/lib/api/hooks";
import { absoluteTime, capitalise, decisionWords, listed, reviewerName } from "@/lib/format";

const CHANNEL: Record<string, string> = {
  slack: "Slack",
  teams: "Teams",
  webhook: "the outbound webhook",
  status_page: "the status page",
  ticket_draft: "the ticket system",
};

type Facts = Record<string, unknown>;

function text(facts: Facts, key: string): string | null {
  const value = facts[key];
  return typeof value === "string" && value ? value : null;
}

function number(facts: Facts, key: string): number {
  const value = facts[key];
  return typeof value === "number" ? value : 0;
}

/** What an entry says happened, as one sentence. Who did it comes separately. */
export function whatHappened(entry: DecisionRecordEntry): string {
  const p = (entry.payload ?? {}) as Facts;
  switch (entry.kind) {
    case "review": {
      const from = text(p, "from_severity");
      const to = text(p, "to_severity");
      const level = from && to && from !== to ? `, ${from} to ${to}` : to ? ` at ${to}` : "";
      const approved = Array.isArray(p.approved_actions) ? p.approved_actions.length : 0;
      const messages = approved
        ? `, and approved ${approved === 1 ? "one message" : `${approved} messages`}`
        : "";
      return `${capitalise(decisionWords(text(p, "decision") ?? "decided"))} the report${level}${messages}.`;
    }
    case "edit": {
      const changed: string[] = [];
      if (text(p, "title")) changed.push("the title");
      if (text(p, "severity")) changed.push(`the level to ${text(p, "severity")}`);
      if (number(p, "summary_lines") > 0) changed.push("the summary");
      const added = number(p, "actions_added");
      if (added > 0) changed.push(`${added === 1 ? "one action" : `${added} actions`}`);
      if (text(p, "note")) changed.push("a note");
      return changed.length ? `Changed ${listed(changed)}.` : "Edited the report.";
    }
    case "publish": {
      const version = number(p, "version");
      const warned = p.valid === false ? ", with validation warnings" : "";
      return `Published the report${version > 1 ? `, version ${version}` : ""}${warned}.`;
    }
    case "send": {
      const channel = CHANNEL[text(p, "channel") ?? ""] ?? text(p, "channel") ?? "a channel";
      const audience = text(p, "audience") ?? "responders";
      const again = p.resent === true ? " again" : "";
      switch (text(p, "status")) {
        case "sent":
          return `Sent the ${audience} update${again} through ${channel}.`;
        case "failed": {
          const problem = text(p, "problem");
          return `Could not deliver the ${audience} update${again} through ${channel}${problem ? `: ${problem}` : ""}.`;
        }
        case "skipped":
          return `Kept the ${audience} update as a preview: ${channel} is not connected.`;
        default:
          return `Tried to send the ${audience} update through ${channel}.`;
      }
    }
    case "blind_check": {
      const aria = text(p, "aria");
      const outside = p.held === false ? ", outside its short list" : "";
      return `Rated the incident blind at ${text(p, "to") ?? "a level"}${aria ? `; ARIA said ${aria}${outside}` : ""}.`;
    }
    case "recalibration":
      return `Recalibrated the severity model to ${text(p, "model_version") ?? "a new version"}.`;
    case "model_swap":
      return `Started using severity model ${text(p, "model_version") ?? "a new version"}.`;
    case "purge": {
      const days = number(p, "days");
      return days
        ? `Purged the incident after ${days} days without a change.`
        : "Purged the incident.";
    }
    case "delete":
      return "Deleted the incident.";
    default:
      return `${capitalise(String(entry.kind).replaceAll("_", " "))}.`;
  }
}

/** Who did it: a person by the name they signed in with, ARIA for its own jobs and automatic
 * approvals, the operator for the command line. */
export function byWhom(actor: string): string {
  return `By ${actor === "system" ? "ARIA" : reviewerName(actor)}`;
}

/** A run's decisions in order: when, what happened and who did it. Each entry is hash-chained
 * to the one before it, so Settings can say whether the whole record still holds. */
export function DecisionRecord({ runId, enabled = true }: { runId: string; enabled?: boolean }) {
  const entries = useRunRecord(runId, enabled);
  return (
    <section aria-labelledby="record-title" className="grid gap-3 rounded-lg bg-raised p-5">
      <h2 id="record-title" className="font-sans text-base font-semibold">
        Decision record
      </h2>
      {entries.isPending ? (
        <LoadingRows rows={2} label="Loading the decision record" />
      ) : entries.isError ? (
        <ErrorState
          title="The decision record could not be loaded"
          error={entries.error}
          onRetry={() => void entries.refetch()}
        />
      ) : entries.data.length === 0 ? (
        <p className="max-w-prose text-sm text-muted-foreground">
          No decisions yet. The record starts when someone reviews this incident.
        </p>
      ) : (
        <ol className="grid gap-2">
          {entries.data.map((entry) => (
            <li
              key={entry.seq}
              className="grid gap-1 rounded-md bg-sunken px-4 py-3 text-sm sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-x-4"
            >
              <time dateTime={entry.ts} className="tabular text-muted-foreground">
                {absoluteTime(entry.ts)}
              </time>
              <div className="grid min-w-0 gap-0.5">
                <p className="wrap-anywhere">{whatHappened(entry)}</p>
                <p className="text-muted-foreground">{byWhom(entry.actor)}</p>
              </div>
            </li>
          ))}
        </ol>
      )}
      <p className="max-w-prose text-xs text-muted-foreground">
        Entries are written once and never changed. Each is hash-chained to the one before it, and
        Settings says whether the whole record still verifies.
      </p>
    </section>
  );
}
