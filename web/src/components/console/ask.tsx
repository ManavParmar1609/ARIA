"use client";

import { ChevronRightIcon } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { PageHeader } from "@/components/console/states";
import {
  Citations,
  EvidenceProvider,
  KIND_LABEL,
  LogLines,
  useEvidence,
} from "@/components/run/evidence";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError } from "@/lib/api/client";
import { useAsk, useRun, useRuns } from "@/lib/api/hooks";
import type { AskResponse, Evidence } from "@/lib/api/types";
import { stripSeverity } from "@/lib/format";
import { cn } from "@/lib/utils";

// Ask ARIA has one job: questions about ARIA's records, answered with their sources (items 21 to
// 23). It says what it can answer, keeps good questions in view, numbers each answer's sources in
// the order they are cited and names them in a list underneath.

const ABOUT_ALL = "all";

const LIBRARY_QUESTIONS = [
  "Have we seen ZooKeeper lose quorum before, and how was it fixed?",
  "What does the runbook say to do first when DataNodes fail to serve blocks?",
  "Which past incidents involved SSH brute-force attempts on many hosts?",
];

const INCIDENT_QUESTIONS = [
  "What did the investigation find?",
  "Which errors appeared most often?",
  "What should I check first?",
];

export interface Turn {
  id: string;
  question: string;
  runId: string | null;
  answer?: AskResponse;
  error?: string;
}

// The conversation outlives a visit to a runbook or another page: Back finds it as it was (N-03).
// Kept for this tab only, and only for answered questions.
const TURNS_KEY = "aria:ask-turns";
const KEPT_TURNS = 10;

export function loadTurns(storage: Pick<Storage, "getItem"> | undefined): Turn[] {
  try {
    const turns: unknown = JSON.parse(storage?.getItem(TURNS_KEY) ?? "[]");
    return Array.isArray(turns)
      ? (turns as Turn[]).filter(
          (t) =>
            typeof t?.id === "string" && typeof t.question === "string" && (t.answer || t.error),
        )
      : [];
  } catch {
    return [];
  }
}

function saveTurns(turns: Turn[]) {
  try {
    const kept = turns.filter((t) => t.answer || t.error).slice(0, KEPT_TURNS);
    window.sessionStorage.setItem(TURNS_KEY, JSON.stringify(kept));
  } catch {
    // Storage full or blocked: the conversation still works, it is just not kept.
  }
}

/**
 * What a screen reader hears about the latest question: the answer replaces the "Searching"
 * line, and a region that appears with its content is not read out, so one region that is always
 * on the page says it. An error is an alert of its own.
 */
export function answerNews(turn: Turn | undefined): string {
  if (!turn || turn.error) return "";
  const answer = turn.answer;
  if (!answer) return "Searching ARIA's records";
  const points = answer.answer.length;
  if (points === 0) return "Nothing in ARIA's records answers this.";
  const sources = sourceNumbers(answer).size;
  const found = answer.insufficient_evidence ? "ARIA found part of an answer" : "ARIA answered";
  return `${found}: ${points} ${points === 1 ? "point" : "points"}, from ${sources} ${
    sources === 1 ? "source" : "sources"
  }.`;
}

/** Each cited source's number: 1 for the first one the answer cites, and so on. */
export function sourceNumbers(answer: Pick<AskResponse, "answer">): Map<string, string> {
  const numbers = new Map<string, string>();
  for (const claim of answer.answer) {
    for (const id of claim.evidence_ids ?? []) {
      if (!numbers.has(id)) numbers.set(id, String(numbers.size + 1));
    }
  }
  return numbers;
}

/**
 * What a source is called in the list, after its kind ("Runbook: ", "Severity rule: "): what it
 * is about, without the IDs its record is titled with ("Rule R12 (floor SEV2): ...", "Runbook
 * hdfs-disk-full: ...", "Similar incident syn-hdfs-1: ... (SEV3; 4x on hdfs)").
 */
const RULE_TITLE = /^Rule \S+ \((?:score|floor) SEV\d\): (.+)$/s;
const RUNBOOK_TITLE = /^Runbook \S+: (.+)$/s;
const INCIDENT_TITLE = /^(?:Similar|Past) incident \S+: (.+?)(?: \(SEV\d[^)]*\))?$/s;

export function sourceName(evidence: Evidence): string {
  const data = (evidence.data ?? {}) as Record<string, unknown>;
  if (evidence.kind === "incident") {
    const title =
      typeof data.title === "string" && data.title
        ? data.title
        : (INCIDENT_TITLE.exec(evidence.title)?.[1] ?? evidence.title);
    return data.synthetic ? `${title} (built from a sample)` : title;
  }
  const rule = evidence.kind === "rule" ? RULE_TITLE.exec(evidence.title) : null;
  if (rule?.[1]) return rule[1];
  const runbook = evidence.kind === "runbook" ? RUNBOOK_TITLE.exec(evidence.title) : null;
  if (runbook?.[1]) return runbook[1];
  return evidence.title;
}

/** Names for a list of sources: two past incidents with one title are told apart by the day each
 * was last seen. */
export function sourceNames(list: Evidence[]): Map<string, string> {
  const names = new Map(list.map((e) => [e.id, sourceName(e)] as const));
  const counts = new Map<string, number>();
  for (const name of names.values()) counts.set(name, (counts.get(name) ?? 0) + 1);
  for (const e of list) {
    const name = names.get(e.id) ?? "";
    if ((counts.get(name) ?? 0) > 1 && e.ts) {
      const day = new Date(e.ts).toLocaleDateString("en-GB", {
        day: "numeric",
        month: "short",
        year: "numeric",
        timeZone: "UTC",
      });
      names.set(e.id, `${name}, last seen ${day}`);
    }
  }
  return names;
}

/** The answer's sources, numbered as cited. A citation clicked above opens its source here. */
function Sources({ id, numbers }: { id: string; numbers: ReadonlyMap<string, string> }) {
  const { byId, active, pinned, linesFor } = useEvidence();
  const names = sourceNames(
    [...numbers.keys()].map((eid) => byId.get(eid)).filter((e): e is Evidence => e != null),
  );
  const rows = useRef(new Map<string, HTMLDetailsElement>());
  useEffect(() => {
    const row = pinned ? rows.current.get(pinned) : undefined;
    if (row) row.open = true;
  }, [pinned]);
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="grid gap-1.5">
      <h3 id={`${id}-title`} className="text-sm font-medium">
        Sources
      </h3>
      <ol className="grid">
        {[...numbers].map(([eid, n]) => {
          const evidence = byId.get(eid);
          if (!evidence) return null;
          const data = (evidence.data ?? {}) as Record<string, unknown>;
          const runbook = typeof data.runbook === "string" ? data.runbook : null;
          const lines = linesFor(eid);
          return (
            <li key={eid}>
              <details
                ref={(el) => {
                  if (el) rows.current.set(eid, el);
                  else rows.current.delete(eid);
                }}
                className={cn(
                  "group rounded-md px-2 transition-colors duration-(--duration-quick)",
                  active === eid && "bg-highlight/60",
                )}
              >
                <summary className="grid cursor-pointer grid-cols-[1.25rem_minmax(0,1fr)_1rem] items-start gap-2 py-1.5 text-sm leading-6 [&::-webkit-details-marker]:hidden">
                  <span className="tabular font-mono text-xs leading-6 text-muted-foreground">
                    {n}
                  </span>
                  <span className="min-w-0 wrap-anywhere">
                    <span className="text-muted-foreground">
                      {KIND_LABEL[evidence.kind] ?? evidence.kind}:
                    </span>{" "}
                    {names.get(eid) ?? sourceName(evidence)}
                  </span>
                  <ChevronRightIcon
                    aria-hidden
                    className="mt-1 size-4 text-muted-foreground transition-transform duration-(--duration-quick) group-open:rotate-90 motion-reduce:transition-none"
                  />
                </summary>
                <div className="grid gap-2 pb-3 pl-7 text-xs leading-5">
                  {evidence.detail ? (
                    <p className="wrap-anywhere whitespace-pre-wrap text-muted-foreground">
                      {evidence.detail}
                    </p>
                  ) : null}
                  {lines.length ? <LogLines lines={lines} limit={4} /> : null}
                  {runbook ? (
                    <Link
                      href={`/console/runbooks/${encodeURIComponent(runbook)}` as never}
                      className="w-fit underline underline-offset-4 hover:text-heading"
                    >
                      Open the runbook
                    </Link>
                  ) : null}
                  {!evidence.detail && !lines.length && !runbook ? (
                    <p className="text-muted-foreground">Recorded by {evidence.source}.</p>
                  ) : null}
                </div>
              </details>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function Answer({ turn }: { turn: Turn }) {
  const answer = turn.answer;
  if (turn.error) {
    return (
      <p role="alert" className="text-sm text-danger">
        {turn.error}
      </p>
    );
  }
  if (!answer) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <span aria-hidden className="block size-2 animate-pulse-dot rounded-full bg-primary" />
        Searching ARIA&apos;s records
      </p>
    );
  }
  const notes = answer.notes?.length ? (
    <ul className="grid gap-1 text-sm text-muted-foreground">
      {answer.notes.map((note) => (
        <li key={note}>{note}</li>
      ))}
    </ul>
  ) : null;
  if (answer.answer.length === 0) {
    return (
      <div className="grid gap-1 text-sm">
        {notes}
        <p>Nothing in ARIA&apos;s records answers this.</p>
        <p className="text-muted-foreground">
          {turn.runId
            ? "Try: ask about the logs, the investigation or what to check first, or pick a question above."
            : "Try: name a system, a part or a kind of failure, such as “ZooKeeper quorum loss”, or pick a question above."}
        </p>
      </div>
    );
  }
  const numbers = sourceNumbers(answer);
  const panelId = `${turn.id}-sources`;
  return (
    <EvidenceProvider evidence={answer.evidence} events={[]} panelId={panelId}>
      <div className="grid gap-4">
        {answer.insufficient_evidence ? (
          <p className="rounded-md bg-sev3/12 p-3 text-sm">
            ARIA found only part of an answer. What it found is below.
          </p>
        ) : null}
        {notes}
        <ul className="grid gap-2.5">
          {answer.answer.map((claim, i) => (
            <li key={i} className="leading-relaxed">
              {claim.text} <Citations ids={claim.evidence_ids ?? []} labels={numbers} />
            </li>
          ))}
        </ul>
        <Sources id={panelId} numbers={numbers} />
        <p className="text-xs text-faint">
          {answer.answered_by === "llm"
            ? `Written by ${answer.model ?? "a language model"} from these sources.`
            : "Put together from ARIA's records, without a language model."}
          {/* Questions about "this incident" asked of the whole library land here. */}
          {turn.runId
            ? ""
            : " This searched all past incidents and runbooks; to ask about one incident, choose it under About."}
        </p>
      </div>
    </EvidenceProvider>
  );
}

function Questions() {
  const id = useId();
  const ask = useAsk();
  const runs = useRuns("all", 30);
  // An incident page's "Ask about this incident" opens here with that incident chosen.
  const linked = useSearchParams().get("run");
  const linkedRun = useRun(linked ?? "", Boolean(linked));
  // A link to an incident this visitor can't see (or that was deleted) falls back to all.
  const missing = Boolean(linked) && linkedRun.isError;
  const [question, setQuestion] = useState("");
  const [chosen, setAbout] = useState<string>(linked ?? ABOUT_ALL);
  const about = missing && chosen === linked ? ABOUT_ALL : chosen;
  // This page renders in the browser only (it reads the address), so storage is there to read.
  const [turns, setTurns] = useState<Turn[]>(() =>
    loadTurns(typeof window === "undefined" ? undefined : window.sessionStorage),
  );
  useEffect(() => saveTurns(turns), [turns]);
  const counter = useRef(0);
  const input = useRef<HTMLInputElement>(null);
  const suggestions = about === ABOUT_ALL ? LIBRARY_QUESTIONS : INCIDENT_QUESTIONS;

  const send = (text: string) => {
    const q = text.trim();
    if (q.length < 3 || ask.isPending) return;
    counter.current += 1;
    const turn: Turn = {
      // Unique beyond this visit too: kept turns come back with their ids.
      id: `${id}-${Date.now().toString(36)}-q${counter.current}`,
      question: q,
      runId: about === ABOUT_ALL ? null : about,
    };
    setTurns((list) => [turn, ...list]);
    setQuestion("");
    ask.mutate(
      { question: q, run_id: turn.runId },
      {
        onSuccess: (answer) =>
          setTurns((list) => list.map((t) => (t.id === turn.id ? { ...t, answer } : t))),
        onError: (error) =>
          setTurns((list) =>
            list.map((t) =>
              t.id === turn.id
                ? { ...t, error: error instanceof ApiError ? error.detail : error.message }
                : t,
            ),
          ),
      },
    );
  };

  return (
    <div className="grid gap-8">
      <form
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          send(question);
          // The button greys out with the box emptied: keep focus where the next question goes.
          input.current?.focus();
        }}
        className="grid gap-4"
      >
        <div className="grid grid-cols-[minmax(0,1fr)] gap-3 md:grid-cols-[minmax(0,1fr)_16rem]">
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-q`}>Your question</Label>
            <Input
              ref={input}
              id={`${id}-q`}
              value={question}
              maxLength={1000}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder={
                about === ABOUT_ALL
                  ? "How was the last ZooKeeper quorum loss fixed?"
                  : "What should I check first for this incident?"
              }
            />
          </div>
          {/* minmax(0, 1fr): a long incident title truncates instead of widening the page. */}
          <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-1.5">
            <Label htmlFor={`${id}-about`}>About</Label>
            <Select value={about} onValueChange={setAbout}>
              <SelectTrigger id={`${id}-about`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="max-w-[min(32rem,calc(100vw-2rem))]">
                <SelectItem value={ABOUT_ALL}>All past incidents</SelectItem>
                {linked && !missing && !runs.data?.runs.some((run) => run.id === linked) ? (
                  <SelectItem value={linked}>
                    {stripSeverity(linkedRun.data?.title ?? "") || "This incident"}
                  </SelectItem>
                ) : null}
                {(runs.data?.runs ?? []).map((run) => (
                  <SelectItem key={run.id} value={run.id}>
                    {/* An example can share a title with a visitor's own run of the sample. */}
                    {stripSeverity(run.title) || run.id}
                    {run.example ? " (example)" : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {missing ? (
              <p className="text-xs text-muted-foreground">
                The incident in the link isn&apos;t available here, so questions go to all past
                incidents.
              </p>
            ) : null}
          </div>
        </div>
        <Button
          type="submit"
          variant="primary"
          className="justify-self-start"
          disabled={question.trim().length < 3 || ask.isPending}
        >
          Ask ARIA
        </Button>
      </form>

      <section aria-labelledby={`${id}-try`} className="grid gap-2">
        <h2 id={`${id}-try`} className="font-sans text-sm font-medium">
          Try one of these
        </h2>
        <ul className="flex flex-wrap gap-2">
          {suggestions.map((s) => (
            <li key={s} className="min-w-0">
              <Button
                size="sm"
                variant="secondary"
                // Questions are long: let them wrap on a phone rather than widen the page.
                className="h-auto min-h-9 py-1.5 text-left whitespace-normal"
                // Not disabled while ARIA answers: focus would fall off the button to the page.
                // A second question waits, as send() ignores it until the first is answered.
                onClick={() => send(s)}
              >
                {s}
              </Button>
            </li>
          ))}
        </ul>
      </section>

      <p role="status" className="sr-only">
        {answerNews(turns[0])}
      </p>
      {turns.length ? (
        <ol aria-label="Answers" className="grid max-w-3xl gap-8">
          {turns.map((turn) => (
            <li key={turn.id} className="grid gap-3 border-t border-rule pt-6">
              <h2 className="text-xl tracking-heading wrap-anywhere">{turn.question}</h2>
              <Answer turn={turn} />
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  );
}

export function Ask() {
  return (
    <div className="grid gap-6">
      <PageHeader
        title="Ask ARIA"
        description="Ask about one incident, or about the past incidents and runbooks ARIA knows. Answers link to what they use. ARIA can't see live systems."
      />
      <Questions />
    </div>
  );
}
