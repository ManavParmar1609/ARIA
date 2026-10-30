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
      return `Not sent${d.problem ? `: ${d.problem}` : "."}`;
    default:
      // Still approved after the run ended: whatever was sending it stopped before it heard back.
      return ended
        ? "Delivery not confirmed: ARIA stopped before it heard back, so this may already have gone out."
        : "Sending now.";
  }
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
}: {
  runId: string;
  deliveries: Delivery[];
  ended: boolean;
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
  return (
    <section aria-labelledby="deliveries-title" className="grid gap-3 rounded-lg bg-raised p-5">
      <h2 id="deliveries-title" className="text-base font-medium">
        Messages
      </h2>
      <ul className="grid gap-2">
        {deliveries.map((d) => (
          <li
            key={d.action_id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-sunken px-4 py-3"
          >
            <div className="grid min-w-0 gap-0.5">
              <p className="truncate font-medium">{d.title}</p>
              <p className="text-sm text-muted-foreground">{outcome(d, ended)}</p>
            </div>
            {canSendAgain(d, ended) ? (
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
    </section>
  );
}
