"use client";

import {
  ArrowUpIcon,
  ArrowUpRightIcon,
  CircleAlertIcon,
  RotateCcwIcon,
  SquarePenIcon,
  XIcon,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { Mark } from "@/components/aria/wordmark";
import { PageHeader } from "@/components/console/states";
import {
  Citations,
  EvidenceProvider,
  KIND_LABEL,
  RawResult,
  sourceLabel,
  useEvidence,
} from "@/components/run/evidence";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/copy-button";
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
import { definitionFor, type Definition } from "@/lib/definitions";
import { evidenceDetail, evidenceTitle } from "@/lib/evidence-text";
import { capitalise, plainTemplate, shortTime, stripSeverity } from "@/lib/format";
import { cn } from "@/lib/utils";

// Ask ARIA is a conversation about ARIA's records: questions about one incident, or about the past
// incidents and runbooks it knows, answered with their sources (items 21 to 23). It reads like a
// chat: your questions on the right, ARIA's answers on the left, each answer's sources numbered in
// the order they are cited and linked to the records they came from.

const ABOUT_ALL = "all";

const LIBRARY_QUESTIONS = [
  "Have we seen ZooKeeper lose quorum before, and how was it fixed?",
  "What does the runbook say to do first when DataNodes fail to serve blocks?",
  "Which past incidents involved SSH brute-force attempts on many hosts?",
  "What should I check first when servers can't look up names?",
];

const INCIDENT_QUESTIONS = [
  "What did the investigation find?",
  "Which errors appeared most often?",
  "What should I check first?",
  "Has this happened before?",
];

/** What ARIA shows, and a screen reader hears, while it works on an answer. */
const THINKING = "ARIA is thinking…";

export interface Turn {
  id: string;
  question: string;
  runId: string | null;
  /** What the question was about, as the About box named it when it was asked. */
  about?: string;
  /** A word's meaning, answered from ARIA's word list rather than a search. */
  definition?: Definition;
  answer?: AskResponse;
  error?: string;
  /** The server was waking up, restarting or busy: a wait, not a fault. */
  unanswered?: boolean;
  /** When ARIA answered, as an ISO time. */
  at?: string;
}

/** Whether ARIA is still working on the question. */
const waiting = (turn: Turn) => !turn.answer && !turn.error && !turn.definition;

// The conversation outlives a visit to a runbook or another page: coming back finds it as it was
// (N-03), a question still being answered included. A reload keeps the answered questions. Kept
// for this tab only, oldest first.
const TURNS_KEY = "aria:ask-chat";
const KEPT_TURNS = 20;

export function loadTurns(storage: Pick<Storage, "getItem"> | undefined): Turn[] {
  try {
    const turns: unknown = JSON.parse(storage?.getItem(TURNS_KEY) ?? "[]");
    return Array.isArray(turns)
      ? (turns as Turn[]).filter(
          (t) => typeof t?.id === "string" && typeof t.question === "string" && !waiting(t),
        )
      : [];
  } catch {
    return [];
  }
}

function tabStorage(): Storage | undefined {
  try {
    return window.sessionStorage;
  } catch {
    return undefined; // the browser blocks storage for this site
  }
}

function saveTurns(turns: Turn[]) {
  try {
    const kept = turns.filter((t) => !waiting(t)).slice(-KEPT_TURNS);
    tabStorage()?.setItem(TURNS_KEY, JSON.stringify(kept));
  } catch {
    // Storage full or blocked: the conversation still works, it is just not kept.
  }
}

// This tab's conversation lives outside React, so an answer that arrives after the page was left
// still lands in it.
let chat: Turn[] | null = null;
const listeners = new Set<() => void>();
const NO_TURNS: Turn[] = [];

function readChat(): Turn[] {
  chat ??= loadTurns(tabStorage());
  return chat;
}

function writeChat(change: (turns: Turn[]) => Turn[]) {
  chat = change(readChat());
  saveTurns(chat);
  for (const listener of listeners) listener();
}

function onChat(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Forget this tab's conversation, in memory and in storage. */
export function resetChat() {
  chat = null;
  try {
    tabStorage()?.removeItem(TURNS_KEY);
  } catch {
    // Blocked storage holds nothing to forget.
  }
  for (const listener of listeners) listener();
}

function useChat(): Turn[] {
  return useSyncExternalStore(onChat, readChat, () => NO_TURNS);
}

let asked = 0;

/** A question's id, unique beyond this visit too: kept questions come back with their ids. */
function newTurnId(): string {
  asked += 1;
  return `q${Date.now().toString(36)}-${asked}`;
}

/** The element that holds one question and its answer. */
const exchangeId = (turnId: string) => `ask-${turnId}`;

/** What a screen reader hears first in an answer: how much it holds. */
export function answerNews(turn: Turn | undefined): string {
  if (!turn || turn.error) return "";
  if (turn.definition)
    return `ARIA answered from its word list: what ${turn.definition.term} means.`;
  const answer = turn.answer;
  if (!answer) return THINKING;
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
 * What a source is called in the list, after its kind ("Runbook", "Severity rule"): what it is
 * about, without the IDs its record is titled with ("Rule R12 (floor SEV2): ...", "Runbook
 * hdfs-disk-full: ...", "Similar incident syn-hdfs-1: ... (SEV3; 4x on hdfs)").
 */
const RULE_TITLE = /^Rule \S+ \((?:score|floor) SEV\d\): (.+)$/s;
const RUNBOOK_TITLE = /^Runbook \S+: (.+)$/s;
const INCIDENT_TITLE = /^(?:Similar|Past) incident \S+: (.+?)(?: \(SEV\d[^)]*\))?$/s;

/** A past incident's own title, without the ID and level its record is titled with. */
function incidentTitle(evidence: Evidence): string {
  const data = (evidence.data ?? {}) as Record<string, unknown>;
  return typeof data.title === "string" && data.title
    ? data.title
    : (INCIDENT_TITLE.exec(evidence.title)?.[1] ?? evidence.title);
}

/** Whether a past incident was built from one of ARIA's samples rather than real history. */
const fromSample = (evidence: Evidence) =>
  evidence.kind === "incident" && Boolean((evidence.data as Record<string, unknown>)?.synthetic);

/** `sample: false` leaves out "(built from a sample)", for a card that says so beside the kind. */
export function sourceName(evidence: Evidence, { sample = true } = {}): string {
  if (evidence.kind === "incident") {
    const title = incidentTitle(evidence);
    return sample && fromSample(evidence) ? `${title} (built from a sample)` : title;
  }
  const rule = evidence.kind === "rule" ? RULE_TITLE.exec(evidence.title) : null;
  if (rule?.[1]) return rule[1];
  const runbook = evidence.kind === "runbook" ? RUNBOOK_TITLE.exec(evidence.title) : null;
  if (runbook?.[1]) return runbook[1];
  const tested = evidence.kind === "hypothesis" ? HYPOTHESIS_TITLE.exec(evidence.title) : null;
  if (tested?.[1] && tested[2]) {
    return `${TESTED[tested[1]] ?? "Still being tested"}: ${plainTemplate(tested[2])}`;
  }
  const check = evidence.kind === "tool" ? TOOL_TITLE.exec(evidence.title) : null;
  if (check?.[1] && check[2]) {
    return `${TOOL_NAMES[check[1]] ?? capitalise(check[1].replaceAll("_", " "))}: ${check[2]}`;
  }
  return evidenceTitle(evidence);
}

// "H2 supported: <statement>" and "component_timeline: <summary>", as the investigator records
// them, read without the investigation's own labels.
const HYPOTHESIS_TITLE = /^H\d+ (\w+): (.+)$/s;
const TESTED: Record<string, string> = {
  supported: "Backed by the evidence",
  refuted: "Ruled out",
};
const TOOL_TITLE = /^([a-z_]+): (.+)$/s;
const TOOL_NAMES: Record<string, string> = {
  search_incidents: "Past incidents searched",
  get_template_examples: "Examples of the pattern",
  node_breakdown: "By server",
  component_timeline: "Over time",
  list_runbooks: "Runbooks that match",
  get_runbook: "The runbook ARIA read",
};

/** Names for a list of sources: two past incidents with one title are told apart by the day each
 * was last seen. */
export function sourceNames(list: Evidence[], { sample = true } = {}): Map<string, string> {
  const names = new Map(list.map((e) => [e.id, sourceName(e, { sample })] as const));
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

/**
 * Where a source can be opened: a runbook on its page, a past incident in the library (or, when
 * ARIA triaged it, on its own page), and anything else a triage recorded on that incident's page.
 */
export function sourceLink(
  evidence: Evidence,
  runId: string | null,
): { href: string; label: string } | null {
  const data = (evidence.data ?? {}) as Record<string, unknown>;
  if (evidence.kind === "runbook") {
    const slug = [data.slug, data.runbook].find((s): s is string => typeof s === "string" && !!s);
    return slug
      ? { href: `/console/runbooks/${encodeURIComponent(slug)}`, label: "Open the runbook" }
      : null;
  }
  if (evidence.kind === "incident") {
    // An approved incident's entry is named after its run: inc-X came from run-X.
    const id = typeof data.incident_id === "string" ? data.incident_id : "";
    if (id.startsWith("inc-")) {
      return {
        href: `/console/runs/run-${encodeURIComponent(id.slice(4))}`,
        label: "Open the incident",
      };
    }
    return {
      href: `/console/memory?q=${encodeURIComponent(incidentTitle(evidence))}`,
      label: "Find it in the incident library",
    };
  }
  return runId
    ? { href: `/console/runs/${encodeURIComponent(runId)}`, label: "Open the incident" }
    : null;
}

/** An answer as text to paste elsewhere: its points with their source numbers, then the sources. */
export function answerText(turn: Turn): string {
  if (turn.definition) return `${turn.definition.term}: ${turn.definition.text}`;
  const answer = turn.answer;
  if (!answer?.answer.length) return "";
  const numbers = sourceNumbers(answer);
  const byId = new Map(answer.evidence.map((e) => [e.id, e] as const));
  const cited = [...numbers.keys()]
    .map((id) => byId.get(id))
    .filter((e): e is Evidence => e != null);
  const names = sourceNames(cited);
  const points = answer.answer.map((claim) => {
    const marks = (claim.evidence_ids ?? []).map((id) => `[${numbers.get(id)}]`).join("");
    return marks ? `${claim.text} ${marks}` : claim.text;
  });
  const sources = cited.map(
    (e) => `${numbers.get(e.id)}. ${KIND_LABEL[e.kind] ?? e.kind}: ${names.get(e.id)}`,
  );
  return [...points, ...(sources.length ? [`Sources:\n${sources.join("\n")}`] : [])].join("\n\n");
}

/**
 * Bring the latest exchange into view above the box, as gently as the reader allows: all of it and
 * whatever follows it when that fits on the screen, else from its start (below the phone's bar).
 */
function revealLatest(exchange: Element | null | undefined) {
  if (!exchange) return;
  const page = document.documentElement;
  const above = parseFloat(window.getComputedStyle(page).scrollPaddingTop) || 0;
  const start = exchange.getBoundingClientRect().top + window.scrollY - above;
  const end = page.scrollHeight - window.innerHeight;
  const top = Math.max(0, Math.min(start, end));
  if (Math.abs(top - window.scrollY) < 2) return;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  window.scrollTo({ top, behavior: reduce ? "auto" : "smooth" });
}

/** True once `ms` have passed since the component mounted. */
function useAfter(ms: number): boolean {
  const [passed, setPassed] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setPassed(true), ms);
    return () => window.clearTimeout(timer);
  }, [ms]);
  return passed;
}

// A new message fades up into place, once; restored ones are simply there.
const ENTER =
  "motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-bottom-2 duration-(--duration-moderate) ease-(--ease-out)";

// ARIA's side: a cream card on the canvas, its tighter corner by the avatar.
const ARIA_CARD =
  "max-w-full rounded-[1.125rem] rounded-tl-[0.375rem] border border-rule bg-raised px-4 py-3.5 wrap-anywhere sm:px-5 sm:py-4";

/** ARIA's avatar beside its card; on a phone it sits above the card, with ARIA's name, so the
 * answer has the screen's width to itself. */
function ReplyRow({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        // minmax(0, 1fr) throughout: a long word wraps instead of widening the column.
        "grid grid-cols-[minmax(0,1fr)] items-start gap-y-1.5 sm:grid-cols-[2rem_minmax(0,1fr)] sm:gap-x-3 sm:pr-10",
        className,
      )}
    >
      <div className="flex items-center gap-2 sm:pt-0.5">
        <Mark className="size-6 rounded-full sm:size-8" />
        <span aria-hidden className="text-xs font-medium text-muted-foreground sm:hidden">
          ARIA
        </span>
      </div>
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] justify-items-start gap-1">
        {children}
      </div>
    </div>
  );
}

/** Three dots while ARIA works, or words for those who asked for less motion. They wait a moment
 * before showing, so a quick answer does not flash them. */
function Thinking() {
  const shown = useAfter(300);
  const row = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (shown) revealLatest(row.current?.closest("article"));
  }, [shown]);
  if (!shown) return null;
  return (
    <div ref={row} className={ENTER}>
      <ReplyRow>
        <div className={cn(ARIA_CARD, "py-3 sm:py-3")}>
          <p className="flex min-h-6 items-center gap-1.5">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                aria-hidden
                className="block size-2 animate-pulse-dot rounded-full bg-muted-foreground motion-reduce:hidden"
                style={{ animationDelay: `${i * 0.2}s` }}
              />
            ))}
            <span className="sr-only text-sm text-muted-foreground motion-reduce:not-sr-only">
              {THINKING}
            </span>
          </p>
        </div>
      </ReplyRow>
    </div>
  );
}

function Notes({ notes }: { notes?: string[] }) {
  if (!notes?.length) return null;
  return (
    <ul className="grid gap-1 text-sm text-muted-foreground">
      {notes.map((note) => (
        <li key={note}>{note}</li>
      ))}
    </ul>
  );
}

/** The source a citation was clicked for: what it says, and the way to its record. */
function SourceDetail({
  panelId,
  numbers,
  names,
  runId,
}: {
  panelId: string;
  numbers: ReadonlyMap<string, string>;
  names: ReadonlyMap<string, string>;
  runId: string | null;
}) {
  const { byId, pinned, origin, pin } = useEvidence();
  const evidence = pinned ? byId.get(pinned) : undefined;
  const n = pinned ? numbers.get(pinned) : undefined;
  const to = evidence ? sourceLink(evidence, runId) : null;
  const data = (evidence?.data ?? {}) as Record<string, unknown>;
  const runbook = evidence?.kind === "incident" && typeof data.runbook === "string" && data.runbook;
  const detail = evidence ? evidenceDetail(evidence) : "";
  // On a phone the page scrolled down to the source; this takes the reader back to the claim.
  const backToClaim = () => {
    if (!origin?.isConnected) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    origin.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
    origin.focus({ preventScroll: true });
  };
  return (
    // Focus lands here after a citation is clicked on a narrow screen (evidence.tsx).
    <div
      id={panelId}
      tabIndex={-1}
      role={evidence ? "region" : undefined}
      aria-label={evidence ? `Source ${n ?? ""}` : undefined}
      className="rounded-xl outline-none empty:hidden focus-visible:ring-2 focus-visible:ring-ring"
    >
      {evidence ? (
        <div className="grid gap-2 rounded-xl bg-sunken p-3.5 text-sm motion-safe:animate-in motion-safe:fade-in-0">
          <div className="flex items-start justify-between gap-2">
            <p className="pt-1 text-xs text-muted-foreground">
              Source {n} · {KIND_LABEL[evidence.kind] ?? evidence.kind}
            </p>
            <Button
              size="icon-sm"
              variant="ghost"
              aria-label={`Close source ${n ?? ""}`}
              className="-mt-1 -mr-1.5"
              onClick={() => pin(null)}
            >
              <XIcon aria-hidden />
            </Button>
          </div>
          <p className="font-medium wrap-anywhere text-heading">
            {names.get(evidence.id) ?? sourceName(evidence)}
          </p>
          {detail ? (
            <p className="wrap-anywhere whitespace-pre-wrap text-muted-foreground">{detail}</p>
          ) : (
            <p className="text-muted-foreground">Recorded by {sourceLabel(evidence.source)}.</p>
          )}
          <RawResult evidence={evidence} />
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            {to ? (
              <Link
                href={to.href as never}
                className="link inline-flex min-h-6 items-center gap-1 text-sm"
              >
                {to.label}
                <ArrowUpRightIcon aria-hidden className="size-3.5" />
              </Link>
            ) : null}
            {runbook ? (
              <Link
                href={`/console/runbooks/${encodeURIComponent(runbook)}` as never}
                className="link inline-flex min-h-6 items-center gap-1 text-sm"
              >
                Open its runbook
                <ArrowUpRightIcon aria-hidden className="size-3.5" />
              </Link>
            ) : null}
            {origin ? (
              <Button
                size="sm"
                variant="ghost"
                className="-ml-2 h-7 px-2 xl:hidden"
                onClick={backToClaim}
              >
                <ArrowUpIcon aria-hidden />
                Back to the claim
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

/** The answer's sources, numbered as cited, each a card that opens its record. A citation pointed
 * at above lights its card; one clicked opens what it says beneath the cards. */
function Sources({
  turn,
  numbers,
  panelId,
}: {
  turn: Turn;
  numbers: ReadonlyMap<string, string>;
  panelId: string;
}) {
  const { byId, active } = useEvidence();
  const cited = [...numbers.keys()]
    .map((eid) => byId.get(eid))
    .filter((e): e is Evidence => e != null);
  const names = sourceNames(cited);
  // A card says "built from a sample" beside the kind, so the title keeps its lines to itself.
  const titles = sourceNames(cited, { sample: false });
  return (
    <section
      aria-labelledby={`${panelId}-title`}
      className="grid gap-2.5 border-t border-rule pt-4"
    >
      <h3 id={`${panelId}-title`} className="text-sm font-semibold">
        Sources
      </h3>
      <ol className="grid grid-cols-[minmax(0,1fr)] gap-2 sm:grid-cols-2">
        {cited.map((evidence) => {
          const to = sourceLink(evidence, turn.runId);
          const look = cn(
            "grid h-full grid-cols-[auto_minmax(0,1fr)_1rem] items-start gap-x-2.5 rounded-xl px-3 py-2.5 transition-colors duration-(--duration-quick)",
            active === evidence.id ? "bg-highlight" : "bg-sunken",
          );
          // Spaces between the parts, so the link's name reads "1 Runbook ZooKeeper ...".
          const body = (
            <>
              <span className="tabular inline-flex h-6 min-w-6 items-center justify-center rounded-xs border border-control px-1.5 font-mono text-xs text-muted-foreground">
                {numbers.get(evidence.id)}
              </span>{" "}
              <span className="grid min-w-0 gap-0.5">
                <span className="text-xs leading-6 text-muted-foreground">
                  {KIND_LABEL[evidence.kind] ?? evidence.kind}
                  {fromSample(evidence) ? ", built from a sample" : ""}
                </span>{" "}
                <span className="line-clamp-3 text-sm font-medium wrap-anywhere text-heading">
                  {titles.get(evidence.id) ?? sourceName(evidence, { sample: false })}
                </span>
              </span>
            </>
          );
          return (
            <li key={evidence.id} className="min-w-0">
              {to ? (
                <Link
                  href={to.href as never}
                  className={cn(look, "group/source hover:bg-highlight")}
                >
                  {body}
                  <ArrowUpRightIcon
                    aria-hidden
                    className="mt-1 size-4 text-muted-foreground transition-transform duration-(--duration-quick) group-hover/source:translate-x-px group-hover/source:-translate-y-px group-hover/source:text-heading"
                  />
                  <span className="sr-only">. {to.label}</span>
                </Link>
              ) : (
                <div className={look}>{body}</div>
              )}
            </li>
          );
        })}
      </ol>
      <SourceDetail panelId={panelId} numbers={numbers} names={names} runId={turn.runId} />
    </section>
  );
}

function Answered({ turn, answer }: { turn: Turn; answer: AskResponse }) {
  const numbers = sourceNumbers(answer);
  const panelId = `${exchangeId(turn.id)}-source`;
  return (
    <EvidenceProvider evidence={answer.evidence} events={[]} panelId={panelId}>
      <div className="grid grid-cols-[minmax(0,1fr)] gap-4">
        <p className="sr-only">{answerNews(turn)}</p>
        {answer.insufficient_evidence ? (
          <p className="rounded-lg bg-sev3/15 px-3 py-2 text-sm">
            ARIA found only part of an answer. What it found is below.
          </p>
        ) : null}
        <Notes notes={answer.notes} />
        <div className="grid grid-cols-[minmax(0,1fr)] gap-3">
          {answer.answer.map((claim, i) => (
            <p key={i}>
              {claim.text} <Citations ids={claim.evidence_ids ?? []} labels={numbers} />
            </p>
          ))}
        </div>
        <Sources turn={turn} numbers={numbers} panelId={panelId} />
        <p className="text-xs text-muted-foreground">
          {answer.answered_by === "llm"
            ? `Written by ${answer.model ?? "a language model"} from these sources.`
            : "Put together from ARIA's records, without a language model."}
          {/* Questions about "this incident" asked of the whole library land here; the line under
              the question says it searched them all. */}
          {turn.runId ? "" : " To ask about one incident, choose it under About."}
        </p>
      </div>
    </EvidenceProvider>
  );
}

function Failure({
  turn,
  onRetry,
  canRetry,
}: {
  turn: Turn;
  onRetry: () => void;
  canRetry: boolean;
}) {
  return (
    <div className="grid justify-items-start gap-3">
      {turn.unanswered ? (
        // A server that is waking up or busy is a wait, not an alarm.
        <p className="flex items-start gap-2.5">
          <span aria-hidden className="mt-2.5 block size-2 shrink-0 rounded-full bg-sev3" />
          <span>{turn.error}</span>
        </p>
      ) : (
        <p className="flex items-start gap-2.5">
          <CircleAlertIcon aria-hidden className="mt-1.5 size-4 shrink-0 text-danger" />
          <span>
            <span className="font-medium text-danger">ARIA couldn&apos;t answer this.</span>{" "}
            <span className="wrap-anywhere text-muted-foreground">
              {capitalise(turn.error ?? "")}
            </span>
          </span>
        </p>
      )}
      <Button size="sm" variant="raised" onClick={onRetry} disabled={!canRetry}>
        <RotateCcwIcon aria-hidden />
        Try again
      </Button>
    </div>
  );
}

/** ARIA's side of one exchange, once it has something to say. */
function Reply({
  turn,
  fresh,
  onRetry,
  canRetry,
}: {
  turn: Turn;
  fresh: boolean;
  onRetry: () => void;
  canRetry: boolean;
}) {
  const answer = turn.answer;
  const text = answerText(turn);
  let body: ReactNode;
  if (turn.definition) {
    body = (
      <div className="grid gap-2">
        <p>
          <strong className="font-semibold text-heading">{turn.definition.term}</strong>:{" "}
          {turn.definition.text}
        </p>
        <p className="text-sm text-muted-foreground">
          From{" "}
          <Link href={"/console/guide#words" as never} className="link">
            Words used in ARIA
          </Link>
          . To ask about incidents, name a system, a part or a kind of failure.
        </p>
      </div>
    );
  } else if (turn.error) {
    body = <Failure turn={turn} onRetry={onRetry} canRetry={canRetry} />;
  } else if (answer && answer.answer.length === 0) {
    body = (
      <div className="grid gap-2">
        <Notes notes={answer.notes} />
        <p>Nothing in ARIA&apos;s records answers this.</p>
        <p className="text-sm text-muted-foreground">
          {turn.runId
            ? "Try asking about its logs, the investigation or what to check first."
            : "Try naming a system, a part or a kind of failure, such as “ZooKeeper quorum loss”."}
        </p>
      </div>
    );
  } else if (answer) {
    body = <Answered turn={turn} answer={answer} />;
  }
  return (
    <ReplyRow className={cn(fresh && ENTER)}>
      <div
        className={cn(
          ARIA_CARD,
          turn.error && !turn.unanswered && "border-transparent bg-danger/10",
          answer?.answer.length && "w-full",
        )}
      >
        {body}
      </div>
      {text || turn.at ? (
        <div className="flex min-h-8 items-center gap-1">
          {text ? (
            <CopyButton text={text} label="this answer" className="-ml-2 px-2 text-xs" />
          ) : null}
          {turn.at ? (
            <time dateTime={turn.at} className="text-xs text-faint">
              {shortTime(turn.at)}
            </time>
          ) : null}
        </div>
      ) : null}
    </ReplyRow>
  );
}

function Exchange({
  turn,
  fresh,
  onRetry,
  canRetry,
}: {
  turn: Turn;
  fresh: boolean;
  onRetry: () => void;
  canRetry: boolean;
}) {
  const id = exchangeId(turn.id);
  return (
    <article id={id} aria-labelledby={`${id}-q`} className="grid grid-cols-[minmax(0,1fr)] gap-3">
      <div
        className={cn(
          "grid grid-cols-[minmax(0,1fr)] justify-items-end gap-1 pl-10 sm:pl-20",
          fresh && ENTER,
        )}
      >
        <h2
          id={`${id}-q`}
          className="max-w-full rounded-[1.125rem] rounded-br-[0.375rem] bg-primary px-4 py-2.5 text-base leading-relaxed font-normal tracking-normal wrap-anywhere whitespace-pre-wrap text-primary-foreground"
        >
          <span className="sr-only">You asked: </span>
          {turn.question}
        </h2>
        {turn.definition ? null : (
          <p className="px-1 text-xs wrap-anywhere text-muted-foreground">
            {turn.runId
              ? `About: ${turn.about ?? "one incident"}`
              : "About: all past incidents and runbooks"}
          </p>
        )}
      </div>
      {waiting(turn) ? (
        <Thinking />
      ) : (
        <Reply turn={turn} fresh={fresh} onRetry={onRetry} canRetry={canRetry} />
      )}
    </article>
  );
}

function Suggestion({
  question,
  onPick,
  className,
}: {
  question: string;
  onPick: (question: string) => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={() => onPick(question)}
      className={cn(
        "border border-rule bg-raised text-left text-sm text-heading transition-colors duration-(--duration-quick) hover:border-control/40 hover:bg-sunken",
        className,
      )}
    >
      {question}
    </button>
  );
}

export function Ask() {
  const id = useId();
  const ask = useAsk();
  const runs = useRuns("all", 30);
  // An incident page's "Ask about this incident" opens here with that incident chosen.
  const linked = useSearchParams().get("run");
  const linkedRun = useRun(linked ?? "", Boolean(linked));
  // A link to an incident this visitor can't see (or that was deleted) falls back to all; so
  // does one the server could not look up just now, which says so and can try again (FL-10).
  const missing = Boolean(linked) && linkedRun.isError;
  const gone =
    linkedRun.error instanceof ApiError && [400, 404, 422].includes(linkedRun.error.status);
  const [chosen, setAbout] = useState<string>(linked ?? ABOUT_ALL);
  // Opening Ask ARIA again, from the sidebar or another incident's link, asks about what the new
  // address names: the page stays mounted, so the choice follows the link (P2).
  const [followed, setFollowed] = useState(linked);
  if (followed !== linked) {
    setFollowed(linked);
    setAbout(linked ?? ABOUT_ALL);
  }
  const about = missing && chosen === linked ? ABOUT_ALL : chosen;

  const turns = useChat();
  // What was already said when the page opened is simply there; new messages fade in.
  const [shownAtOpen] = useState(() => new Set(turns.map((t) => t.id)));
  const pending = turns.some(waiting);
  const [question, setQuestion] = useState("");
  // A question asked while ARIA answers another waits in the box, said so, rather than being
  // dropped (FL-06).
  const [held, setHeld] = useState(false);
  // The conversation "New chat" put aside, until the next question.
  const [putAside, setPutAside] = useState<Turn[] | null>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const dock = useRef<HTMLDivElement>(null);
  const suggestions = about === ABOUT_ALL ? LIBRARY_QUESTIONS : INCIDENT_QUESTIONS;

  /** The incident's title as the About box shows it. */
  const aboutName = (runId: string): string => {
    const run = runs.data?.runs.find((r) => r.id === runId);
    const title = run?.title ?? (runId === linked ? linkedRun.data?.title : undefined);
    return stripSeverity(title ?? "") || "this incident";
  };

  const focusComposer = () => box.current?.focus({ preventScroll: true });

  const settle = (turnId: string, outcome: Partial<Turn>) =>
    writeChat((list) => list.map((t) => (t.id === turnId ? { ...t, ...outcome } : t)));

  const request = (turn: Turn) => {
    void ask.mutateAsync({ question: turn.question, run_id: turn.runId }).then(
      (answer) => settle(turn.id, { answer, at: new Date().toISOString() }),
      (error: unknown) =>
        settle(turn.id, {
          error: error instanceof Error ? error.message : "Something went wrong on ARIA's side.",
          // Asleep, restarting or busy: a wait, not a fault (client.ts).
          unanswered: error instanceof ApiError && (error.unreachable || error.status === 429),
          at: new Date().toISOString(),
        }),
    );
  };

  const send = (text: string) => {
    const q = text.trim();
    if (q.length < 3) return;
    if (pending) {
      setQuestion(q);
      setHeld(true);
      return;
    }
    setHeld(false);
    setPutAside(null);
    setQuestion("");
    const turn: Turn = {
      id: newTurnId(),
      question: q,
      runId: about === ABOUT_ALL ? null : about,
      about: about === ABOUT_ALL ? undefined : aboutName(about),
    };
    const meaning = definitionFor(q);
    if (meaning) {
      // A word's meaning comes from the word list, whatever the About box says.
      const answered = { ...turn, runId: null, about: undefined, definition: meaning };
      writeChat((list) => [...list, { ...answered, at: new Date().toISOString() }]);
      return;
    }
    writeChat((list) => [...list, turn]);
    request(turn);
  };

  // After every question, focus goes back to the box, ready for the next one.
  const sendAndStay = (text: string) => {
    send(text);
    focusComposer();
  };

  const retry = (turn: Turn) => {
    if (pending) return;
    const again: Turn = {
      id: turn.id,
      question: turn.question,
      runId: turn.runId,
      about: turn.about,
    };
    writeChat((list) => list.map((t) => (t.id === turn.id ? again : t)));
    request(again);
    focusComposer();
  };

  const newChat = () => {
    // A question still being answered is dropped with the rest: its answer has nowhere to land.
    setPutAside(turns.filter((t) => !waiting(t)));
    setHeld(false);
    resetChat();
    focusComposer();
  };

  const undoNewChat = () => {
    const kept = putAside;
    setPutAside(null);
    if (kept?.length) writeChat(() => kept);
    focusComposer();
  };

  // New messages come into view above the box: the question as it is sent, then its answer. A
  // conversation found on arrival opens at its latest message, as a chat does.
  const last = turns.at(-1);
  const lastId = last?.id ?? "";
  const lastSettled = last ? !waiting(last) : false;
  const seen = useRef<string | null>(null);
  useEffect(() => {
    const key = `${lastId}:${lastSettled}`;
    const arriving = seen.current === null;
    if (seen.current === key) return;
    seen.current = key;
    if (!lastId) return;
    if (arriving) {
      window.scrollTo({ top: document.documentElement.scrollHeight });
      return;
    }
    revealLatest(document.getElementById(exchangeId(lastId)));
  }, [lastId, lastSettled]);

  // The box stays at the bottom of the screen, so the page keeps its height clear when it scrolls
  // a message or a focused control into view: nothing lands behind the box (WCAG 2.4.11).
  useEffect(() => {
    const element = dock.current;
    const page = document.documentElement;
    if (!element) return;
    let height = element.offsetHeight;
    const fit = () => {
      const now = element.offsetHeight;
      page.style.setProperty("scroll-padding-bottom", `${now + 16}px`);
      // The box grew (a longer question, a note above it): a reader at the foot of the
      // conversation stays there, so the latest message does not slip behind the box.
      const grew = now - height;
      height = now;
      if (grew > 0 && page.scrollHeight - window.innerHeight - window.scrollY <= grew + 2) {
        window.scrollBy({ top: grew });
      }
    };
    fit();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(fit);
    observer?.observe(element);
    return () => {
      observer?.disconnect();
      page.style.removeProperty("scroll-padding-bottom");
    };
  }, []);

  // The box grows with the question, up to about seven lines, then scrolls.
  useLayoutEffect(() => {
    const element = box.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 192)}px`;
  }, [question]);

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends; Shift+Enter starts a new line, and Enter that picks a word from an input
    // method's list does neither.
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    send(question);
  };

  const askedAlready = new Set(turns.map((t) => t.question));
  const more = suggestions.filter((s) => !askedAlready.has(s));
  const showMore = last && !waiting(last) && !last.error && more.length > 0;

  return (
    // The column runs to the foot of the page, so the box rests at the bottom of the screen.
    <div className="mx-auto -mb-8 flex min-h-[calc(100dvh-6.25rem)] w-full max-w-[46rem] flex-col lg:-mb-12 lg:min-h-[calc(100dvh-3rem)]">
      <PageHeader
        title="Ask ARIA"
        actions={
          turns.length ? (
            <Button size="sm" variant="raised" onClick={newChat}>
              <SquarePenIcon aria-hidden />
              New chat
            </Button>
          ) : null
        }
      />

      {turns.length === 0 ? (
        <section aria-labelledby={`${id}-try`} className="my-auto grid gap-8 pt-8 pb-10">
          <div className="grid justify-items-start gap-4">
            <Mark className="size-11 rounded-full" />
            <div className="grid gap-2">
              <p className="text-statement">What would you like to know?</p>
              <p className="max-w-prose text-muted-foreground">
                {about === ABOUT_ALL
                  ? "ARIA answers from its incident library and runbooks, or from one incident you choose under About. Every answer links to its sources. ARIA can't see live systems."
                  : "ARIA answers from this incident's logs and what its investigation found, and links every answer to its sources. ARIA can't see live systems."}
              </p>
            </div>
          </div>
          <div className="grid gap-3">
            <h2 id={`${id}-try`} className="text-sm font-semibold">
              Try one of these
            </h2>
            <ul className="grid grid-cols-[minmax(0,1fr)] gap-2 sm:grid-cols-2">
              {suggestions.map((s) => (
                <li key={s} className="flex">
                  <Suggestion
                    question={s}
                    onPick={sendAndStay}
                    className="w-full rounded-2xl px-4 py-3 leading-snug"
                  />
                </li>
              ))}
            </ul>
          </div>
        </section>
      ) : null}

      {/* The conversation: a log, so a screen reader hears each new message as it arrives. */}
      <div
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        aria-label="Conversation"
        className={cn("grid grid-cols-[minmax(0,1fr)] gap-8", turns.length > 0 && "mt-6")}
      >
        {turns.map((turn) => (
          <Exchange
            key={turn.id}
            turn={turn}
            fresh={!shownAtOpen.has(turn.id)}
            onRetry={() => retry(turn)}
            canRetry={!pending}
          />
        ))}
      </div>

      {showMore ? (
        <section aria-labelledby={`${id}-more`} className="mt-6 grid gap-2 pl-[2.375rem] sm:pl-11">
          <h2 id={`${id}-more`} className="text-xs font-medium text-muted-foreground">
            You could also ask
          </h2>
          <ul className="flex flex-wrap gap-2">
            {more.map((s) => (
              <li key={s} className="max-w-full min-w-0">
                <Suggestion
                  question={s}
                  onPick={sendAndStay}
                  className="min-h-9 rounded-[1.125rem] px-3.5 py-1.5"
                />
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <div
        ref={dock}
        className="sticky bottom-0 z-20 mt-auto bg-app pt-4 pb-[max(1rem,env(safe-area-inset-bottom))] sm:pt-6"
      >
        <div role="status" className="grid gap-1 text-sm text-muted-foreground">
          {missing ? (
            <p className="mb-2 px-1">
              {gone
                ? "The incident in the link isn't available here, so questions go to all past incidents."
                : "ARIA couldn't look up the incident in the link just now, so questions go to all past incidents. "}
              {gone ? null : (
                <button
                  type="button"
                  onClick={() => void linkedRun.refetch()}
                  className="min-h-6 font-medium text-foreground underline underline-offset-2"
                >
                  Try again
                </button>
              )}
            </p>
          ) : null}
          {held && pending ? (
            <p className="mb-2 px-1">
              ARIA is still answering the last question. Yours is in the box: send it once that
              answer arrives.
            </p>
          ) : null}
          {putAside && turns.length === 0 ? (
            <p className="mb-1 flex flex-wrap items-center gap-x-2 px-1">
              Started a new chat.
              {putAside.length ? (
                <Button size="sm" variant="link" className="h-6" onClick={undoNewChat}>
                  Bring back the last one
                </Button>
              ) : null}
            </p>
          ) : null}
        </div>
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            sendAndStay(question);
          }}
          className="grid rounded-[1.375rem] border border-control bg-raised transition-[border-color,box-shadow] duration-(--duration-quick) has-[textarea:focus]:border-ring has-[textarea:focus]:ring-1 has-[textarea:focus]:ring-ring"
        >
          <label htmlFor={`${id}-q`} className="sr-only">
            Your question
          </label>
          <textarea
            ref={box}
            id={`${id}-q`}
            rows={1}
            value={question}
            maxLength={1000}
            enterKeyHint="send"
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={onKeyDown}
            // Short enough for one line on the narrowest phone; the greeting says what to ask.
            placeholder={about === ABOUT_ALL ? "Ask a question" : "Ask about this incident"}
            className="block max-h-48 w-full resize-none bg-transparent px-4 pt-3.5 pb-1 text-base leading-relaxed text-foreground outline-none placeholder:text-muted-foreground"
          />
          <div className="flex items-center justify-between gap-3 p-2 pl-3">
            {/* minmax(0, 1fr): a long incident title truncates instead of widening the page. */}
            <div className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-1.5">
              <Label htmlFor={`${id}-about`} className="text-xs text-muted-foreground">
                About
              </Label>
              <Select value={about} onValueChange={setAbout}>
                <SelectTrigger
                  id={`${id}-about`}
                  className="h-8 w-auto max-w-full gap-1.5 rounded-full border-transparent bg-sunken px-3 text-sm hover:bg-foreground/8 [&>svg]:shrink-0"
                >
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
            </div>
            <button
              type="submit"
              aria-label="Send question"
              disabled={question.trim().length < 3 || pending}
              className="grid size-9 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground transition-[background-color,opacity,scale] duration-(--duration-quick) ease-(--ease-out) hover:bg-primary-hover active:scale-95 disabled:pointer-events-none disabled:opacity-35"
            >
              <ArrowUpIcon aria-hidden className="size-[1.125rem]" strokeWidth={2.25} />
            </button>
          </div>
        </form>
        <p className="mt-2 hidden px-4 text-xs text-faint sm:block [@media(pointer:coarse)]:hidden">
          <kbd className="rounded-xs border border-control/60 px-1 font-sans">Enter</kbd> sends,{" "}
          <kbd className="rounded-xs border border-control/60 px-1 font-sans">Shift</kbd>{" "}
          <kbd className="rounded-xs border border-control/60 px-1 font-sans">Enter</kbd> starts a
          new line
        </p>
      </div>
    </div>
  );
}
