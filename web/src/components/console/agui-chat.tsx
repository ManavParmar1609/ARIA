"use client";

import { HttpAgent, type AgentSubscriber } from "@ag-ui/client";
import {
  BotIcon,
  CircleCheckIcon,
  ShieldAlertIcon,
  UserRoundCheckIcon,
  WrenchIcon,
} from "lucide-react";
import Link from "next/link";
import { useId, useRef, useState, type FormEvent } from "react";

import { SeverityBadge } from "@/components/aria/severity";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Markdown } from "@/components/ui/markdown";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import samples from "@/data/samples.json";
import { isSeverity } from "@/lib/api/types";
import { SYSTEM_NAMES } from "@/lib/systems";
import { cn } from "@/lib/utils";

/** One thing that happened in the chat, rendered in order. */
type Item =
  | { kind: "user"; id: string; lines: number; system: string }
  | { kind: "step"; id: string; name: string; done: boolean }
  | { kind: "tool"; id: string; name: string; args: string; result?: string }
  | { kind: "text"; id: string; text: string; done: boolean }
  | { kind: "signal"; id: string; name: string; value: unknown }
  | {
      kind: "review";
      id: string;
      interruptId: string;
      message: string;
      meta: Record<string, unknown>;
      answered?: string;
    }
  | { kind: "done"; id: string; status: string; runId?: string }
  | { kind: "error"; id: string; message: string };

const uid = () => Math.random().toString(36).slice(2, 10);

const STEP: Record<string, string> = {
  plan: "Planning",
  parse_shard: "Parsing logs",
  merge: "Merging",
  severity: "Rating severity",
  recall: "Recalling similar incidents",
  investigate: "Investigating",
  assess: "Checking the evidence",
  widen: "Widening the search",
  report: "Writing the report",
  comms: "Drafting messages",
  review: "Waiting for review",
  publish: "Publishing",
  reject: "Rejecting",
};

/**
 * Triage in a chat, over the AG-UI protocol: the same stream any AG-UI client (CopilotKit
 * included) receives. Steps, tool calls and the report arrive as events; the review arrives as
 * an interrupt, answered here with a resume entry.
 */
export function AguiChat() {
  const id = useId();
  const [items, setItems] = useState<Item[]>([]);
  // While a review waits for an answer, its approve button is the one primary action.
  const awaiting = items.some((i) => i.kind === "review" && !i.answered);
  const [system, setSystem] = useState("hdfs");
  const [text, setText] = useState("");
  // A loaded sample is semi-synthetic, so its run never counts as a real incident in memory.
  const [sample, setSample] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const agentRef = useRef<HttpAgent | null>(null);

  const push = (item: Item) => setItems((list) => [...list, item]);
  const update = (match: (item: Item) => boolean, change: (item: Item) => Item) =>
    setItems((list) => {
      const index = list.findLastIndex(match);
      if (index < 0) return list;
      const next = [...list];
      next[index] = change(next[index] as Item);
      return next;
    });

  const subscriber: AgentSubscriber = {
    onStepStartedEvent: ({ event }) =>
      push({ kind: "step", id: uid(), name: event.stepName, done: false }),
    onStepFinishedEvent: ({ event }) =>
      update(
        (i) => i.kind === "step" && i.name === event.stepName && !i.done,
        (i) => ({ ...i, done: true }) as Item,
      ),
    onToolCallStartEvent: ({ event }) =>
      push({ kind: "tool", id: event.toolCallId, name: event.toolCallName, args: "" }),
    onToolCallArgsEvent: ({ event }) =>
      update(
        (i) => i.kind === "tool" && i.id === event.toolCallId,
        (i) => ({ ...i, args: (i as { args: string }).args + event.delta }) as Item,
      ),
    onToolCallResultEvent: ({ event }) =>
      update(
        (i) => i.kind === "tool" && i.id === event.toolCallId,
        (i) => ({ ...i, result: event.content }) as Item,
      ),
    onTextMessageStartEvent: ({ event }) =>
      push({ kind: "text", id: event.messageId, text: "", done: false }),
    onTextMessageContentEvent: ({ event }) =>
      update(
        (i) => i.kind === "text" && i.id === event.messageId,
        (i) => ({ ...i, text: (i as { text: string }).text + event.delta }) as Item,
      ),
    onTextMessageEndEvent: ({ event }) =>
      update(
        (i) => i.kind === "text" && i.id === event.messageId,
        (i) => ({ ...i, done: true }) as Item,
      ),
    onCustomEvent: ({ event }) => {
      if (event.name === "aria.guardrail" || event.name === "aria.replan") {
        push({ kind: "signal", id: uid(), name: event.name, value: event.value });
      }
    },
    onRunErrorEvent: ({ event }) => push({ kind: "error", id: uid(), message: event.message }),
    onRunFinishedEvent: ({ event }) => {
      const outcome = (
        event as {
          outcome?: {
            type?: string;
            interrupts?: { id: string; message?: string; metadata?: Record<string, unknown> }[];
          };
        }
      ).outcome;
      if (outcome?.type === "interrupt" && outcome.interrupts?.length) {
        const first = outcome.interrupts[0];
        if (first) {
          push({
            kind: "review",
            id: uid(),
            interruptId: first.id,
            message: first.message ?? "Review the report.",
            meta: first.metadata ?? {},
          });
        }
      } else {
        const result = (event as { result?: { status?: string; run_id?: string } }).result ?? {};
        push({
          kind: "done",
          id: uid(),
          status: result.status ?? "finished",
          runId: result.run_id,
        });
      }
    },
  };

  const start = async (event: FormEvent) => {
    event.preventDefault();
    const lines = text.split(/\r?\n/).filter((l) => l.trim());
    if (lines.length === 0 || running) return;
    const agent = new HttpAgent({ url: "/api/agui", threadId: `chat-${uid()}${uid()}` });
    agentRef.current = agent;
    setItems([{ kind: "user", id: uid(), lines: lines.length, system }]);
    agent.addMessage({ id: uid(), role: "user", content: lines.join("\n") });
    setRunning(true);
    try {
      await agent.runAgent({ forwardedProps: { system, synthetic: sample !== null } }, subscriber);
    } catch (error) {
      push({
        kind: "error",
        id: uid(),
        message: error instanceof Error ? error.message : "The run failed.",
      });
    } finally {
      setRunning(false);
    }
  };

  const answer = async (
    review: Extract<Item, { kind: "review" }>,
    decision: "approve" | "reject",
  ) => {
    const agent = agentRef.current;
    if (!agent || running) return;
    update(
      (i) => i.id === review.id,
      (i) => ({ ...i, answered: decision }) as Item,
    );
    setRunning(true);
    try {
      await agent.runAgent(
        {
          resume: [
            {
              interruptId: review.interruptId,
              status: "resolved",
              payload:
                decision === "approve"
                  ? { decision: "approve" }
                  : { decision: "reject", comment: "rejected in chat" },
            },
          ],
        },
        subscriber,
      );
    } catch (error) {
      push({
        kind: "error",
        id: uid(),
        message: error instanceof Error ? error.message : "The review failed.",
      });
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="grid gap-6">
      <p className="max-w-3xl text-muted-foreground">
        Paste logs and ARIA triages them here, over the AG-UI protocol: each step, tool call and the
        report stream in as events, and the review comes back as an interrupt you answer below.
      </p>

      {items.length > 0 ? (
        <ol aria-label="Triage conversation" aria-live="polite" className="grid gap-2">
          {items.map((item) => {
            switch (item.kind) {
              case "user":
                return (
                  <li
                    key={item.id}
                    className="justify-self-end rounded-md bg-sunken px-4 py-2.5 text-sm"
                  >
                    {item.lines} {SYSTEM_NAMES[item.system] ?? item.system} log lines
                  </li>
                );
              case "step":
                return (
                  <li
                    key={item.id}
                    className="flex items-center gap-2 text-sm text-muted-foreground"
                  >
                    {item.done ? (
                      <CircleCheckIcon aria-hidden className="size-4 text-ok" />
                    ) : (
                      <span
                        aria-hidden
                        className="block size-2 animate-pulse-dot rounded-full bg-primary"
                      />
                    )}
                    {STEP[item.name] ?? item.name}
                  </li>
                );
              case "tool":
                return (
                  <li key={item.id} className="grid gap-1 rounded-lg bg-sunken p-3 text-xs">
                    <p className="flex items-center gap-2 font-mono">
                      <WrenchIcon aria-hidden className="size-3.5 text-faint" />
                      {item.name}({item.args.replace(/^\{|\}$/g, "")})
                    </p>
                    {item.result ? (
                      <p className="text-muted-foreground">
                        {(() => {
                          try {
                            return (
                              (JSON.parse(item.result) as { summary?: string }).summary ??
                              item.result
                            );
                          } catch {
                            return item.result;
                          }
                        })()}
                      </p>
                    ) : null}
                  </li>
                );
              case "signal":
                return (
                  <li key={item.id} className="flex items-center gap-2 text-sm text-sev3-fg">
                    <ShieldAlertIcon aria-hidden className="size-4" />
                    {item.name === "aria.guardrail"
                      ? `Guardrail: ${String((item.value as { quarantined?: number })?.quarantined ?? 0)} line(s) quarantined`
                      : "Replanned: widening the search"}
                  </li>
                );
              case "text":
                return (
                  <li key={item.id} className="grid gap-2 rounded-lg bg-raised p-5">
                    <p className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                      <BotIcon aria-hidden className="size-4" />
                      ARIA&apos;s report{item.done ? "" : " (streaming)"}
                    </p>
                    <div
                      tabIndex={0}
                      role="region"
                      aria-label="Report"
                      className="max-h-[32rem] overflow-auto"
                    >
                      <Markdown>{item.text}</Markdown>
                    </div>
                  </li>
                );
              case "review": {
                const sev = item.meta.severity;
                return (
                  <li
                    key={item.id}
                    className="grid gap-3 rounded-lg bg-raised p-5 ring-1 ring-primary/50"
                  >
                    <p className="flex items-center gap-2 font-medium">
                      <UserRoundCheckIcon aria-hidden className="size-4 text-primary" />
                      {item.message}
                    </p>
                    <p className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                      <SeverityBadge severity={isSeverity(sev) ? sev : null} size="sm" />
                      {String(item.meta.title ?? "")}
                    </p>
                    {item.answered ? (
                      <p className="text-sm">You chose to {item.answered}.</p>
                    ) : (
                      <div className="flex gap-2">
                        <Button
                          size="sm"
                          variant="primary"
                          disabled={running}
                          onClick={() => void answer(item, "approve")}
                        >
                          Approve and publish
                        </Button>
                        <Button
                          size="sm"
                          variant="danger"
                          disabled={running}
                          onClick={() => void answer(item, "reject")}
                        >
                          Discard the draft
                        </Button>
                      </div>
                    )}
                  </li>
                );
              }
              case "done":
                return (
                  <li key={item.id} className="text-sm">
                    Run {item.status}.{" "}
                    {item.runId ? (
                      <Link
                        href={`/console/runs/${encodeURIComponent(item.runId)}` as never}
                        className="underline decoration-control underline-offset-4"
                      >
                        Open it in the console
                      </Link>
                    ) : null}
                  </li>
                );
              case "error":
                return (
                  <li key={item.id} role="alert" className="text-sm text-danger">
                    {item.message}
                  </li>
                );
              default:
                return null;
            }
          })}
        </ol>
      ) : null}

      <form onSubmit={(e) => void start(e)} className="grid gap-3 rounded-lg bg-raised p-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-system`}>Log format</Label>
            <Select value={system} onValueChange={setSystem}>
              <SelectTrigger id={`${id}-system`} className="w-48">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(SYSTEM_NAMES).map(([value, name]) => (
                  <SelectItem key={value} value={value}>
                    {name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {samples.slice(0, 3).map((s) => (
              <Button
                key={s.id}
                size="sm"
                variant="ghost"
                className="h-auto min-h-8 shrink py-1.5 text-left whitespace-normal"
                onClick={() => {
                  setSample(s.id);
                  setSystem(s.system);
                  setText(s.lines.join("\n"));
                }}
              >
                Sample: {s.label}
              </Button>
            ))}
          </div>
        </div>
        <Label htmlFor={`${id}-logs`} className="sr-only">
          Log lines
        </Label>
        <Textarea
          id={`${id}-logs`}
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={6}
          wrap="off"
          spellCheck={false}
          placeholder="Paste log lines, one per line"
          className={cn("font-mono text-xs leading-5")}
        />
        <Button
          type="submit"
          variant={awaiting ? "secondary" : "primary"}
          className="justify-self-start"
          disabled={running || !text.trim()}
        >
          {running ? "ARIA is working" : "Triage in chat"}
        </Button>
      </form>
    </div>
  );
}
