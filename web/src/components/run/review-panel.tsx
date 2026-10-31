"use client";

import { ChevronDownIcon, CircleCheckIcon, TriangleAlertIcon } from "lucide-react";
import { useId, useRef, useState } from "react";

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
  type ReportEdits,
  type ReviewPrompt,
  type Severity,
} from "@/lib/api/types";
import { stripSeverity } from "@/lib/format";
import { LEVEL_WORD, orList } from "@/lib/levels";
import { cn } from "@/lib/utils";

const KIND: Record<string, string> = {
  slack: "Slack",
  teams: "Teams",
  webhook: "Webhook",
  status_page: "Status page",
  ticket_draft: "Ticket draft",
};

/** One message ARIA drafted. With a connected channel it has a box to tick; without one it is a
 * preview to read, with nothing to tick. */
function ActionChoice({
  action,
  checked,
  onChange,
}: {
  action: OutboundAction;
  checked?: boolean;
  onChange?: (value: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const name = (
    <>
      <span className="font-medium">
        {KIND[action.kind] ?? action.kind} to {action.audience}
      </span>
      <span className="truncate text-muted-foreground">{action.title}</span>
    </>
  );
  return (
    <li className="grid gap-2 rounded-md bg-sunken p-3">
      <div className="flex items-start gap-3">
        {onChange ? (
          <>
            <input
              id={id}
              type="checkbox"
              checked={checked ?? false}
              onChange={(e) => onChange(e.target.checked)}
              className="mt-1 size-4 shrink-0 accent-(--primary)"
            />
            <label htmlFor={id} className="grid min-w-0 flex-1 gap-0.5 text-sm">
              {name}
            </label>
          </>
        ) : (
          <p className="grid min-w-0 flex-1 gap-0.5 text-sm">{name}</p>
        )}
        {/* No channel to send it to: it stays a preview, and says so. */}
        {onChange ? null : (
          <span className="mt-0.5 shrink-0 rounded-full border border-rule px-2 text-xs leading-5 text-muted-foreground">
            Preview
          </span>
        )}
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
        // As it would arrive in a chat: who it is from and to, then the text.
        <div
          tabIndex={0}
          role="region"
          aria-label="Message"
          className="max-h-64 overflow-auto rounded-md bg-raised p-3 ring-1 ring-rule"
        >
          <p className="flex items-center gap-2 text-xs">
            <span
              aria-hidden
              className="grid size-5 place-items-center rounded-sm bg-primary text-xs font-medium text-primary-foreground"
            >
              A
            </span>
            <span className="font-medium">ARIA</span>
            <span className="text-muted-foreground">to {action.audience}</span>
          </p>
          <p className="mt-2 text-sm leading-6 whitespace-pre-wrap">{action.body}</p>
        </div>
      ) : null}
    </li>
  );
}

/** The non-blank lines of a text box, trimmed. */
const lines = (text: string) =>
  text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

export type EditForm = {
  title: string;
  severity: Severity;
  summary: string;
  addActions: string;
  note: string;
};

/** What the reviewer changed in the edit form, and nothing else: a field sent back unchanged
 * would count as an edit, and an unchanged summary would lose the evidence its lines cite. */
export function changedEdits(
  edit: EditForm,
  original: { title: string; severity: Severity; summary: string[] },
): ReportEdits {
  const title = edit.title.trim();
  const summary = lines(edit.summary);
  return {
    title: title && title !== original.title ? title : undefined,
    severity: edit.severity !== original.severity ? edit.severity : undefined,
    summary: summary.join("\n") !== original.summary.join("\n") ? summary : undefined,
    add_actions: lines(edit.addActions),
    note: edit.note.trim() || undefined,
  };
}

/** Whether the edits change anything, judged as the server judges them (an empty summary keeps
 * the report's own). */
export function hasChanges(edits: ReportEdits): boolean {
  return Boolean(
    edits.title ||
    edits.severity ||
    edits.summary?.length ||
    edits.add_actions?.length ||
    edits.note,
  );
}

/** What approving does, in the button's words: a message goes out only when one is ticked and
 * its channel is connected. */
export function approveLabel(sending: number, pending: boolean): string {
  if (pending) return "Saving";
  return sending > 0 ? "Approve and send" : "Approve and publish";
}

/** The decision ARIA is waiting for. The buttons come first and say what each one does; ARIA's
 * own check sits beside them as advice, because only a person's approval sends anything. */
export function ReviewPanel({
  runId,
  prompt,
  actions,
  report,
  onDecided,
}: {
  runId: string;
  prompt: ReviewPrompt;
  actions: OutboundAction[];
  report: IncidentReport | undefined;
  /** Called once the decision is saved; the page then shows its receipt in this place. */
  onDecided?: () => void;
}) {
  const id = useId();
  const review = useReview(runId);
  const settings = useSettingsView();
  const [send, setSend] = useState<Set<string>>(new Set());
  const [comment, setComment] = useState("");
  const [editing, setEditing] = useState(false);
  const [unchanged, setUnchanged] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const original = {
    title: stripSeverity(report?.title ?? prompt.title),
    severity: prompt.severity,
    summary: (report?.summary ?? []).map((c) => c.text),
  };
  const [edit, setEdit] = useState<EditForm>({
    title: original.title,
    severity: original.severity,
    summary: original.summary.join("\n"),
    addActions: "",
    note: "",
  });
  const change = (patch: Partial<EditForm>) => {
    setEdit({ ...edit, ...patch });
    setUnchanged(false);
  };
  const publishEdits = () => {
    if (hasChanges(changedEdits(edit, original))) void decide("edit");
    else setUnchanged(true);
  };
  const error = review.error instanceof ApiError ? review.error.detail : review.error?.message;
  const proposed = actions.filter((a) => a.status === "proposed" || a.status === undefined);
  // A message can go out only through a connected channel; the others stay previews, with
  // nothing to tick. Until the settings load, every message reads as a preview.
  const channels = settings.data?.channels ?? {};
  const sendable = proposed.filter((a) => channels[a.kind]);
  const previews = proposed.filter((a) => !channels[a.kind]);
  const sending = sendable.filter((a) => send.has(a.action_id)).length;
  const validation = report?.validation;

  // The dialogs open from these buttons, not from triggers of their own, so closing one puts
  // focus back by hand: otherwise it falls to the page and the next key press is a shortcut.
  const editButton = useRef<HTMLButtonElement>(null);
  const discardButton = useRef<HTMLButtonElement>(null);
  const backTo = (event: Event, button: HTMLButtonElement | null) => {
    if (!button?.isConnected) return; // decided: the receipt has taken the panel's place
    event.preventDefault();
    button.focus();
  };

  const saving = useRef(false);
  const decide = async (decision: "approve" | "edit" | "reject") => {
    if (saving.current) return;
    saving.current = true;
    const edits = decision === "edit" ? changedEdits(edit, original) : undefined;
    try {
      await review.mutateAsync({
        decision,
        comment: comment.trim() || undefined,
        edits,
        approve_actions:
          decision === "reject"
            ? []
            : sendable.filter((a) => send.has(a.action_id)).map((a) => a.action_id),
      });
    } catch {
      return; // the panel shows the error
    } finally {
      saving.current = false;
    }
    // No toast: the receipt that takes this panel's place says what happened.
    setEditing(false);
    setDiscarding(false);
    onDecided?.();
  };

  return (
    <section
      aria-labelledby={`${id}-title`}
      className="grid gap-4 rounded-lg bg-raised p-5 ring-1 ring-primary/50"
    >
      <div className="grid gap-1">
        <h2
          id={`${id}-title`}
          className="flex items-center gap-2 font-sans text-base font-semibold"
        >
          {/* A still dot: the severity stamp is this page's one entrance animation. */}
          <span aria-hidden className="block size-2 rounded-full bg-primary" />
          Waiting for your review
        </h2>
        <p className="text-sm text-muted-foreground">
          Nothing has been sent. Approving publishes the report
          {sendable.length ? " and sends the messages you tick" : ""}.{" "}
          {report ? (
            // The report sits below the panels it rests on: a way down before deciding.
            <a
              href="#report-title"
              className="text-foreground underline decoration-control underline-offset-2 hover:decoration-foreground"
            >
              Read the report first
            </a>
          ) : null}
        </p>
      </div>
      <div className="grid gap-2">
        <div className="flex flex-wrap gap-2">
          <Button
            variant="primary"
            onClick={() => void decide("approve")}
            disabled={review.isPending}
          >
            {approveLabel(sending, review.isPending)}
          </Button>
          <Button
            ref={editButton}
            onClick={() => {
              // Start from the report as it is now: it may have arrived after this panel did, and
              // an empty summary box would read as "no summary" (lines kept keep their sources).
              setEdit({ ...edit, title: original.title, summary: original.summary.join("\n") });
              setEditing(true);
            }}
            disabled={review.isPending}
          >
            Edit before sending
          </Button>
          <Button
            ref={discardButton}
            variant="danger"
            onClick={() => setDiscarding(true)}
            disabled={review.isPending}
          >
            Discard draft
          </Button>
        </div>
        {validation?.ok ? (
          <p className="flex gap-1.5 text-xs text-muted-foreground">
            <CircleCheckIcon aria-hidden className="mt-px size-3.5 shrink-0 text-ok" />
            ARIA&rsquo;s own check: all {validation.checked_claims} claims cite their evidence. It
            is advice; your approval decides.
          </p>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
      {prompt.needs_review ? (
        <p className="flex gap-2 rounded-md bg-sev3/12 p-2.5 text-sm">
          <TriangleAlertIcon aria-hidden className="mt-0.5 size-4 shrink-0 text-sev3-fg" />
          <span>
            {prompt.prediction_set.length > 1
              ? `ARIA isn't sure whether this is ${orList(prompt.prediction_set)}.`
              : `ARIA isn't sure enough of ${prompt.severity} to decide alone.`}{" "}
            Check the severity before approving, or change it with Edit before sending.
          </span>
        </p>
      ) : null}
      {!prompt.valid ? (
        <p className="flex gap-2 rounded-md bg-danger/10 p-2.5 text-sm text-danger">
          <TriangleAlertIcon aria-hidden className="mt-0.5 size-4 shrink-0" />
          ARIA&rsquo;s own check failed on this report. Edit it before sending, or discard it.
        </p>
      ) : null}
      {sendable.length > 0 ? (
        <fieldset className="grid gap-2">
          <legend className="mb-1 text-sm font-medium">Messages to send when you approve</legend>
          <ul className="grid gap-2">
            {sendable.map((action) => (
              <ActionChoice
                key={action.action_id}
                action={action}
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
      {previews.length > 0 ? (
        <details className="group text-sm">
          <summary className="w-fit cursor-pointer py-0.5 font-medium">
            {previews.length} message {previews.length === 1 ? "preview" : "previews"}
            <span className="font-normal text-muted-foreground">
              {" "}
              (no channel is connected for {previews.length === 1 ? "it" : "them"} on this server)
            </span>
          </summary>
          <ul className="mt-2 grid gap-2">
            {previews.map((action) => (
              <ActionChoice key={action.action_id} action={action} />
            ))}
          </ul>
        </details>
      ) : null}
      <details className="text-sm" open={comment ? true : undefined}>
        <summary className="w-fit cursor-pointer py-0.5 text-muted-foreground hover:text-heading">
          Add a comment
        </summary>
        <div className="grid gap-1.5 pt-2">
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
      </details>

      <Dialog open={editing} onOpenChange={setEditing}>
        <DialogContent
          className="max-w-2xl"
          // The dialog itself takes focus, so its title is read first and the report's title is
          // not selected for the first key press to replace (nor a phone's keyboard opened).
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            (event.currentTarget as HTMLElement | null)?.focus();
          }}
          onCloseAutoFocus={(event) => backTo(event, editButton.current)}
        >
          <DialogHeader>
            <DialogTitle>Edit the report before sending</DialogTitle>
            <DialogDescription>
              Your changes are kept with the review and ARIA checks the report again. Saving them
              approves the edited report.
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
                  onChange={(e) => change({ title: e.target.value })}
                />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor={`${id}-edit-sev`}>Severity</Label>
                <Select
                  value={edit.severity}
                  onValueChange={(v) => change({ severity: v as Severity })}
                >
                  <SelectTrigger id={`${id}-edit-sev`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SEVERITIES.map((s) => (
                      <SelectItem key={s} value={s}>
                        {s} · {LEVEL_WORD[s]}
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
                aria-describedby={`${id}-edit-summary-hint`}
                onChange={(e) => change({ summary: e.target.value })}
              />
              <p id={`${id}-edit-summary-hint`} className="text-xs text-muted-foreground">
                A line you leave as it is keeps its sources; a line you change or add cites your
                review.
              </p>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={`${id}-edit-actions`}>Add next steps, one per line</Label>
              <Textarea
                id={`${id}-edit-actions`}
                rows={2}
                value={edit.addActions}
                onChange={(e) => change({ addActions: e.target.value })}
              />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor={`${id}-edit-note`}>Note for the record</Label>
              <Input
                id={`${id}-edit-note`}
                value={edit.note}
                onChange={(e) => change({ note: e.target.value })}
              />
            </div>
          </div>
          {error ? (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : null}
          {unchanged ? (
            <p role="alert" className="text-sm text-muted-foreground">
              Nothing has changed yet. Change the report above, or keep reviewing and approve it as
              it is.
            </p>
          ) : null}
          <DialogFooter>
            <Button onClick={() => setEditing(false)}>Keep reviewing</Button>
            <Button variant="primary" onClick={publishEdits} disabled={review.isPending}>
              {review.isPending
                ? "Saving"
                : sending > 0
                  ? "Approve and send with my edits"
                  : "Approve with my edits"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={discarding} onOpenChange={setDiscarding}>
        <DialogContent onCloseAutoFocus={(event) => backTo(event, discardButton.current)}>
          <DialogHeader>
            <DialogTitle>Discard this draft?</DialogTitle>
            <DialogDescription>
              Nothing is sent, and the incident is closed. A reason, if you give one, is kept with
              this incident&rsquo;s review.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-discard-reason`}>
              Reason <span className="font-normal text-muted-foreground">(optional)</span>
            </Label>
            <Textarea
              id={`${id}-discard-reason`}
              rows={3}
              value={comment}
              maxLength={2000}
              onChange={(e) => setComment(e.target.value)}
            />
          </div>
          {error ? (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : null}
          <DialogFooter>
            <Button onClick={() => setDiscarding(false)}>Keep reviewing</Button>
            <Button
              variant="danger"
              onClick={() => void decide("reject")}
              disabled={review.isPending}
            >
              {review.isPending ? "Discarding" : "Discard the draft"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
