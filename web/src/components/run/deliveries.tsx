"use client";

import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import { useResend } from "@/lib/api/hooks";
import type { Delivery } from "@/lib/api/types";
import { absoluteTime } from "@/lib/format";

const CHANNEL: Record<string, string> = {
  slack: "Slack",
  teams: "Teams",
  webhook: "the outbound webhook",
  status_page: "the status page",
  ticket_draft: "the ticket system",
};

// Words, not colours: the label is the state (DESIGN.md).
function outcome(d: Delivery, ended: boolean): string {
  const channel = CHANNEL[d.kind] ?? d.kind;
  switch (d.status) {
    case "sent":
      return `Sent to ${d.audience} through ${channel}${d.sent_at ? ` at ${absoluteTime(d.sent_at)}` : ""}.`;
    case "failed":
      return `Not delivered through ${channel}${d.problem ? `: ${d.problem}` : "."}`;
    case "skipped":
      // Working as designed, not an error: no channel was connected, so ARIA kept the draft.
      return `Kept as a preview: ${channel} is not connected on this server.`;
    default:
      // Still approved after the run ended: whatever was sending it stopped before it heard back.
      return ended
        ? "Delivery not confirmed: ARIA stopped before it heard back, so this may already have gone out."
        : "Sending now.";
  }
}

/** The server setting that connects a channel, read from the server's own note ("X is not set"). */
export function settingFor(d: Delivery): string | null {
  return /^([A-Z][A-Z0-9_]*) is not set$/.exec(d.problem ?? "")?.[1] ?? null;
}

/** One note for the messages ARIA kept as previews, instead of an error under each of them. */
export function previewNote(deliveries: Delivery[]): string | null {
  const kept = deliveries.filter((d) => d.status === "skipped");
  if (!kept.length) return null;
  if (kept.length === deliveries.length) {
    return "No channel is connected on this server, so ARIA kept every message as a preview. Nothing left this site.";
  }
  const names = [...new Set(kept.map((d) => CHANNEL[d.kind] ?? d.kind))];
  const list =
    names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names.at(-1)}` : (names[0] ?? "");
  return `${list} ${names.length > 1 ? "are" : "is"} not connected on this server, so ARIA kept ${
    kept.length > 1 ? "those messages as previews" : "that message as a preview"
  }.`;
}

/** Whether a message can be sent again: it failed, or the run ended before its delivery was
 * confirmed. The server sends it with the same idempotency key, so a receiver that keeps those
 * does not post it twice. */
export function canSendAgain(d: Delivery, ended: boolean): boolean {
  return d.status === "failed" || (ended && d.status === "approved");
}

/** The messages a reviewer approved, what happened to each, and a way to send one again. */
export function Deliveries({
  runId,
  deliveries,
  ended,
  readOnly = false,
}: {
  runId: string;
  deliveries: Delivery[];
  ended: boolean;
  /** An example on a shared demo: nobody may send its messages again. */
  readOnly?: boolean;
}) {
  const resend = useResend(runId);
  if (!deliveries.length) return null;
  const sendAgain = (d: Delivery) =>
    resend.mutate(d.action_id, {
      onSuccess: (detail) => {
        const now = detail.deliveries?.find((x) => x.action_id === d.action_id);
        if (now?.status === "sent") toast.success("Sent", { description: d.title });
        else toast.error("Still not delivered", { description: now?.problem ?? d.title });
      },
      onError: (error) =>
        toast.error("Not sent again", {
          description: error instanceof ApiError ? error.message : String(error),
        }),
    });
  const note = previewNote(deliveries);
  const settings = [
    ...new Set(deliveries.map(settingFor).filter((name): name is string => name !== null)),
  ];
  return (
    <section aria-labelledby="deliveries-title" className="grid gap-3 rounded-lg bg-raised p-5">
      <h2 id="deliveries-title" className="font-sans text-base font-semibold">
        Messages
      </h2>
      {note ? <p className="max-w-prose text-sm text-muted-foreground">{note}</p> : null}
      <ul className="grid gap-2">
        {deliveries.map((d) => (
          <li
            key={d.action_id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-sunken px-4 py-3"
          >
            <div className="grid min-w-0 gap-0.5">
              <p className="flex min-w-0 items-center gap-2 font-medium">
                {d.status === "skipped" ? (
                  <span className="shrink-0 rounded-sm border border-rule px-1.5 text-xs font-normal text-muted-foreground">
                    Preview
                  </span>
                ) : null}
                <span className="truncate">{d.title}</span>
              </p>
              <p className="text-sm text-muted-foreground">{outcome(d, ended)}</p>
            </div>
            {canSendAgain(d, ended) && !readOnly ? (
              <Button
                size="sm"
                variant="secondary"
                disabled={resend.isPending}
                onClick={() => sendAgain(d)}
              >
                {resend.isPending && resend.variables === d.action_id ? "Sending…" : "Send again"}
              </Button>
            ) : null}
          </li>
        ))}
      </ul>
      {settings.length ? (
        <details className="text-sm text-muted-foreground">
          <summary className="w-fit cursor-pointer text-foreground">Connect a channel</summary>
          <p className="mt-2 max-w-prose">
            If you run ARIA yourself, set{" "}
            {settings.map((name, i) => (
              <span key={name}>
                {i ? (i === settings.length - 1 ? " and " : ", ") : null}
                <code className="font-mono text-xs">{name}</code>
              </span>
            ))}{" "}
            on the server to the channel&apos;s webhook address. Messages approved after that are
            sent.
          </p>
        </details>
      ) : null}
    </section>
  );
}
