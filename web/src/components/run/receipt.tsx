"use client";

import { CircleCheckIcon, CircleXIcon, DownloadIcon } from "lucide-react";
import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import type { Delivery, OutboundAction } from "@/lib/api/types";
import { absoluteTime, shortTime } from "@/lib/format";

// After the review, the panel that asked for it becomes a receipt in the same place: who decided
// and when, and what happened to each message, with the report to download (item 18).

export interface ReceiptFacts {
  status: string;
  decision: string;
  reviewer: string;
  /** The reviewer is the person reading this page. */
  you: boolean;
  /** When the decision was saved. */
  at: string;
  /** The messages ARIA drafted, and the ones the reviewer approved with what became of them. */
  actions: OutboundAction[];
  deliveries: Delivery[];
  /** Whether a message's channel is connected on this server. */
  connected: (kind: string) => boolean;
}

const AUTO = "aria:auto";

function who(reviewer: string, you: boolean): string {
  if (you) return "you";
  return reviewer === "cli" ? "the command line" : reviewer;
}

const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** The receipt in words: who decided and when, then what happened to the messages. */
export function receiptText(f: ReceiptFacts): { decision: string; messages: string | null } {
  const time = shortTime(f.at);
  const by = who(f.reviewer, f.you);
  const decision =
    f.reviewer === AUTO
      ? `Published at ${time} without review: approval was off for this incident.`
      : f.status === "rejected"
        ? `Drafted by ARIA, discarded by ${by} at ${time}.`
        : f.decision === "edit"
          ? `Drafted by ARIA, edited and approved by ${by} at ${time}.`
          : `Drafted by ARIA, approved by ${by} at ${time}.`;
  if (f.status === "rejected") return { decision, messages: "Nothing was sent." };
  if (!f.actions.length) return { decision, messages: null };
  const approved = new Set(f.deliveries.map((d) => d.action_id));
  const sent = f.deliveries.filter((d) => d.status === "sent").length;
  const failed = f.deliveries.filter((d) => d.status === "failed").length;
  const sending = f.deliveries.filter((d) => d.status === "approved").length;
  const kept = [
    ...f.actions.filter((a) => !approved.has(a.action_id)),
    ...f.deliveries.filter((d) => d.status === "skipped"),
  ];
  const parts: string[] = [];
  if (sent) parts.push(`${count(sent, "message", "messages")} sent`);
  if (sending) parts.push(`${count(sending, "message", "messages")} still sending`);
  if (failed) parts.push(`${count(failed, "message", "messages")} not delivered (see below)`);
  if (kept.length) {
    const unconnected = kept.filter((k) => !f.connected(k.kind)).length;
    const why =
      unconnected === kept.length
        ? " (no channel connected)"
        : unconnected === 0
          ? " (not chosen)"
          : "";
    parts.push(`${count(kept.length, "preview", "previews")} kept${why}`);
  }
  const text = parts.join(", ");
  return { decision, messages: `${text.charAt(0).toUpperCase()}${text.slice(1)}.` };
}

export function Receipt({
  runId,
  facts,
  comment,
  focusOnMount = false,
}: {
  runId: string;
  facts: ReceiptFacts;
  comment?: string | null;
  /** Take focus when it replaces the review panel the reader just used. */
  focusOnMount?: boolean;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (focusOnMount) heading.current?.focus();
  }, [focusOnMount]);
  const text = receiptText(facts);
  const rejected = facts.status === "rejected";
  const base = `/api/v1/runs/${encodeURIComponent(runId)}`;
  return (
    <section aria-labelledby="receipt-title" className="grid gap-3 rounded-lg bg-raised p-5">
      <h2
        id="receipt-title"
        ref={heading}
        tabIndex={-1}
        className="flex items-center gap-2 font-sans text-base font-semibold focus:outline-none"
      >
        {rejected ? (
          <CircleXIcon aria-hidden className="size-4 text-muted-foreground" />
        ) : (
          <CircleCheckIcon aria-hidden className="size-4 text-ok" />
        )}
        {rejected ? "Draft discarded" : "Published"}
      </h2>
      <p className="text-sm" title={absoluteTime(facts.at)}>
        {text.decision} {text.messages}
      </p>
      {comment ? (
        <p className="text-sm text-muted-foreground">
          Comment: <q>{comment}</q>
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button asChild size="sm">
          <a href={`${base}/report.md`} download={`${runId}-report.md`}>
            <DownloadIcon aria-hidden />
            Download the report
          </a>
        </Button>
        {rejected ? null : (
          <Button asChild size="sm" variant="ghost">
            <a href={`${base}/postmortem.md`} download={`${runId}-postmortem.md`}>
              <DownloadIcon aria-hidden />
              Download the postmortem draft
            </a>
          </Button>
        )}
      </div>
    </section>
  );
}
