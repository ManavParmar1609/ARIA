"use client";

import { ChevronDownIcon, TriangleAlertIcon } from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError } from "@/lib/api/client";
import { useReview, useSettingsView } from "@/lib/api/hooks";
import {
  SEVERITIES,
  type IncidentReport,
  type OutboundAction,
  type ReviewPrompt,
  type Severity,
} from "@/lib/api/types";
import { stripSeverity } from "@/lib/format";
import { cn } from "@/lib/utils";

const KIND: Record<string, string> = {
  slack: "Slack",
  teams: "Teams",
  webhook: "Webhook",
  status_page: "Status page",
  ticket_draft: "Ticket draft",
};

function ActionChoice({
  action,
  checked,
  onChange,
  ready,
}: {
  action: OutboundAction;
  checked: boolean;
  onChange: (value: boolean) => void;
  /** Whether the channel's webhook is set; unknown until the settings load. */
  ready: boolean | undefined;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <li className="grid gap-2 rounded-md bg-sunken p-3">
      <div className="flex items-start gap-3">
        <input
          id={id}
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          className="mt-1 size-4 shrink-0 accent-(--primary)"
        />
        <label htmlFor={id} className="grid min-w-0 flex-1 gap-0.5 text-sm">
          <span className="font-medium">
            {KIND[action.kind] ?? action.kind} to {action.audience}
          </span>
          <span className="truncate text-muted-foreground">{action.title}</span>
          {ready === false ? (
            <span className="text-xs text-muted-foreground">
              This channel has no webhook set, so the message would be skipped.
            </span>
          ) : null}
        </label>
        <Button
          size="icon-sm"
          variant="ghost"
          aria-expanded={open}
          aria-label={open ? "Hide the message" : "Show the message"}
          onClick={() => setOpen(!open)}
        >
          <ChevronDownIcon
            aria-hidden
            className={cn("transition-transform duration-(--duration-quick)", open && "rotate-180")}
          />
        </Button>
      </div>
      {open ? (
        <pre
          tabIndex={0}
          role="region"
          aria-label="Message"
          className="max-h-56 overflow-auto rounded-sm bg-sunken p-2.5 font-sans text-xs leading-5 whitespace-pre-wrap"
        >
          {action.body}
        </pre>
      ) : null}
    </li>
  );
}

/** The decision ARIA is waiting for: approve, edit or reject, and which messages may go out. */
export function ReviewPanel({
  runId,
  prompt,
  actions,
  report,
}: {
  runId: string;
  prompt: ReviewPrompt;
  actions: OutboundAction[];
  report: IncidentReport | undefined;
}) {
  const id = useId();
  const review = useReview(runId);
  const settings = useSettingsView();
  const [send, setSend] = useState<Set<string>>(new Set());
  const [comment, setComment] = useState("");
  const [editing, setEditing] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [edit, setEdit] = useState({
    title: stripSeverity(report?.title ?? prompt.title),
    severity: prompt.severity,
    summary: (report?.summary ?? []).map((c) => c.text).join("\n"),
    addActions: "",
    note: "",
  });
  const error = review.error instanceof ApiError ? review.error.detail : review.error?.message;
  const proposed = actions.filter((a) => a.status === "proposed" || a.status === undefined);

  const decide = (decision: "approve" | "edit" | "reject") => {
    const edits =
      decision === "edit"
        ? {
            title: edit.title.trim() || undefined,
            severity: edit.severity,
            summary: edit.summary
              .split("\n")
              .map((l) => l.trim())
              .filter(Boolean),
            add_actions: edit.addActions
              .split("\n")
              .map((l) => l.trim())
              .filter(Boolean),
            note: edit.note.trim() || undefined,
          }
        : undefined;
    review.mutate(
      {
        decision,
        comment: comment.trim() || undefined,
        edits,
        approve_actions: decision === "reject" ? [] : [...send],
      },
      {
        onSuccess: (detail) => {
          setEditing(false);
          setRejecting(false);
          const label =
            detail.status === "published"
              ? "Published"
              : detail.status === "rejected"
                ? "Rejected"
                : "Saved";
          if (decision === "reject") {
            toast.success(label, { description: "The report was rejected; nothing was sent." });
            return;
          }
          // What was delivered, not what was ticked: a receiver can be down or not configured.
          const deliveries = detail.deliveries ?? [];
          const sent = deliveries.filter((d) => d.status === "sent").length;
          const missed = deliveries.length - sent;
          const said = sent
            ? `${sent} ${sent === 1 ? "message was" : "messages were"} sent.`
            : "No messages were sent.";
          if (missed) {
            toast.warning(label, {
              description: `${said} ${missed} could not be delivered: see Messages on this page.`,
            });
          } else {
            toast.success(label, { description: said });
          }
        },
      },
    );
  };

  return (
    <section
      aria-labelledby={`${id}-title`}
      className="grid gap-4 rounded-lg bg-raised p-5 ring-1 ring-primary/50"
    >
      <div className="grid gap-1">
        <h2 id={`${id}-title`} className="flex items-center gap-2 text-base font-medium">
          <span
            aria-hidden
            className="block size-2 animate-pulse-dot-thrice rounded-full bg-primary"
          />
          Waiting for your review
        </h2>
        <p className="text-sm text-muted-foreground">
          Nothing has been sent. Approve to publish the report; tick the messages you want sent with
          it.
        </p>
      </div>
      {prompt.needs_review ? (
        <p className="flex gap-2 rounded-md bg-sev3/12 p-2.5 text-sm">
          <TriangleAlertIcon aria-hidden className="mt-0.5 size-4 shrink-0 text-sev3-fg" />
          <span>
            ARIA was unsure about the severity ({prompt.prediction_set.join(" or ")}). Check it
            before approving, or edit it.
          </span>
        </p>
      ) : null}
      {!prompt.valid ? (
        <p className="flex gap-2 rounded-md bg-danger/10 p-2.5 text-sm text-danger">
          <TriangleAlertIcon aria-hidden className="mt-0.5 size-4 shrink-0" />
          The report failed validation. Edit or reject it.
        </p>
      ) : null}
      {proposed.length > 0 ? (
        <fieldset className="grid gap-2">
          <legend className="mb-1 text-sm font-medium">Messages to send on approval</legend>
          <ul className="grid gap-2">
            {proposed.map((action) => (
              <ActionChoice
                key={action.action_id}
                action={action}
                ready={settings.data?.channels?.[action.kind]}
                checked={send.has(action.action_id)}
                onChange={(on) =>
                  setSend((current) => {
                    const next = new Set(current);
                    if (on) next.add(action.action_id);
                    else next.delete(action.action_id);
                    return next;
                  })
                }
              />
            ))}
          </ul>
        </fieldset>
      ) : null}
      <div className="grid gap-1.5">
        <Label htmlFor={`${id}-comment`}>
          Comment{" "}
          <span className="font-normal text-muted-foreground">
            (optional, kept with the report)
          </span>
        </Label>
        <Textarea
          id={`${id}-comment`}
          value={comment}
          maxLength={2000}
          rows={2}
          onChange={(e) => setComment(e.target.value)}
        />
      </div>
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" onClick={() => decide("approve")} disabled={review.isPending}>
          {review.isPending
            ? "Saving"
            : send.size > 0
              ? `Approve and send ${send.size}`
              : "Approve and publish"}
        </Button>
        <Button onClick={() => setEditing(true)} disabled={review.isPending}>
          Edit first
        </Button>
        <Button variant="danger" onClick={() => setRejecting(true)} disabled={review.isPending}>
          Reject
        </Button>
      </div>

      <Dialog open={editing} onOpenChange={setEditing}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Edit the report, then publish</DialogTitle>
            <DialogDescription>
              Your changes are recorded as review evidence, and the report is validated again.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4">
            <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_10rem]">
              <div className="grid gap-1.5">
                <Label htmlFor={`${id}-edit-title`}>Title</Label>
                <Input
                  id={`${id}-edit-title`}
                  value={edit.title}
                  maxLength={200}
                  onChange={(e) => setEdit({ ...edit, title: e.target.value })}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor={`${id}-edit-sev`}>Severity</Label>
                <Select
                  value={edit.severity}
                  onValueChange={(v) => setEdit({ ...edit, severity: v as Severity })}
                >
                  <SelectTrigger id={`${id}-edit-sev`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SEVERITIES.map((s) => (
                      <SelectItem key={s} value={s}>
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={`${id}-edit-summary`}>Summary, one statement per line</Label>
              <Textarea
                id={`${id}-edit-summary`}
                rows={5}
                value={edit.summary}
                onChange={(e) => setEdit({ ...edit, summary: e.target.value })}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={`${id}-edit-actions`}>Add next steps, one per line</Label>
              <Textarea
                id={`${id}-edit-actions`}
                rows={2}
                value={edit.addActions}
                onChange={(e) => setEdit({ ...edit, addActions: e.target.value })}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={`${id}-edit-note`}>Note for the record</Label>
              <Input
                id={`${id}-edit-note`}
                value={edit.note}
                onChange={(e) => setEdit({ ...edit, note: e.target.value })}
              />
            </div>
          </div>
          {error ? (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : null}
          <DialogFooter>
            <Button onClick={() => setEditing(false)}>Keep reviewing</Button>
            <Button variant="primary" onClick={() => decide("edit")} disabled={review.isPending}>
              {review.isPending ? "Publishing" : "Publish with my edits"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={rejecting} onOpenChange={setRejecting}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject this report?</DialogTitle>
            <DialogDescription>
              Nothing will be sent, and the run ends. Say why, so the next run learns from it.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-reject-reason`}>Reason</Label>
            <Textarea
              id={`${id}-reject-reason`}
              rows={3}
              value={comment}
              maxLength={2000}
              onChange={(e) => setComment(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button onClick={() => setRejecting(false)}>Keep reviewing</Button>
            <Button variant="danger" onClick={() => decide("reject")} disabled={review.isPending}>
              {review.isPending ? "Rejecting" : "Reject the report"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
