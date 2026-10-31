"use client";

import { ArrowDownIcon, ArrowRightIcon, ArrowUpIcon, PinIcon, XIcon } from "lucide-react";
import Link from "next/link";
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
  type ReactNode,
} from "react";

import { Button } from "@/components/ui/button";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/popover";
import type { Evidence, LogEvent, TemplateStat } from "@/lib/api/types";
import { chance, evidenceDetail, evidenceTitle, featureName, rawResult } from "@/lib/evidence-text";
import { failureName } from "@/lib/failure-modes";
import { cn } from "@/lib/utils";

const SOURCE_LABEL: Record<string, string> = {
  parser: "the log parser",
  "parser.flows": "the log parser",
  guardrail: "the injection guard",
  "severity.rules": "the severity rules",
  "severity.model": "the severity model",
  "severity.ticket_model": "the ticket model",
  scenario_policy: "the sample's policy",
  investigator: "the investigation",
  reviewer: "the review",
  curated: "the incident library",
  run: "an approved incident",
  "memory.search": "the incident library",
  "memory.feedback": "reviewers' past corrections",
  "mcp.search_incidents": "the incident library",
  "mcp.ticket_history": "the ticket history",
  "mcp.get_runbook": "the runbooks",
  "mcp.search_runbooks": "the runbooks",
  "mcp.get_incident": "the incident library",
  "mcp.summarize_incident": "the incident library",
  "mcp.get_ticket_history": "the ticket history",
  "mcp.search_logs": "the logs",
  "mcp.get_template_examples": "the logs",
  "mcp.component_timeline": "the logs",
  "mcp.node_breakdown": "the logs",
};

/** Where evidence came from, in words: "the severity rules" rather than "severity.rules". */
export const sourceLabel = (source: string) =>
  SOURCE_LABEL[source] ?? (source.startsWith("mcp.") ? "ARIA's read-only tools" : source);

export const KIND_LABEL: Record<string, string> = {
  log: "Log line",
  template: "Log template",
  feature: "Measurement",
  rule: "Severity rule",
  model: "Estimate",
  alert: "Alert",
  incident: "Past incident",
  tickets: "Ticket history",
  runbook: "Runbook",
  tool: "Investigation check",
  hypothesis: "Tested cause",
  feedback: "Reviewer feedback",
  review: "Review",
};

interface EvidenceState {
  byId: Map<string, Evidence>;
  events: LogEvent[];
  active: string | null;
  pinned: string | null;
  /** The citation that pinned the evidence, so a phone reader can get back to the claim. */
  origin: HTMLElement | null;
  /** Whether that citation comes after the panel on the page, so the way back points down. */
  originBelow: boolean;
  /** The element that shows a pinned citation: the evidence panel, or an answer's sources. */
  panelId: string;
  /** Where the panel sits beside the text (a media query): pointing at a citation fills it there,
   * so no card opens on top to say the same. */
  besidePanel: string | null;
  hover: (id: string | null) => void;
  pin: (id: string | null, from?: HTMLElement | null) => void;
  linesFor: (id: string) => LogEvent[];
}

const Ctx = createContext<EvidenceState | null>(null);

/**
 * Which evidence the reader is looking at. Hover or focus previews a citation; a click pins it
 * so it stays in the panel while the reader moves on.
 */
export function EvidenceProvider({
  evidence,
  events,
  panelId = "evidence-panel",
  besidePanel = null,
  children,
}: {
  evidence: Evidence[];
  events: LogEvent[];
  panelId?: string;
  besidePanel?: string | null;
  children: ReactNode;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const [origin, setOrigin] = useState<HTMLElement | null>(null);
  const [originBelow, setOriginBelow] = useState(false);
  const pin = useCallback(
    (id: string | null, from: HTMLElement | null = null) => {
      setPinned(id);
      setOrigin(id ? from : null);
      // In one column the page reads in document order, and the panel sits above the report, so
      // most claims are below it; one in "How serious" is above it (L5).
      const panel = id && from ? document.getElementById(panelId) : null;
      setOriginBelow(
        Boolean(
          from && panel && panel.compareDocumentPosition(from) & Node.DOCUMENT_POSITION_FOLLOWING,
        ),
      );
    },
    [panelId],
  );
  const byId = useMemo(() => new Map(evidence.map((e) => [e.id, e])), [evidence]);
  const byTemplate = useMemo(() => {
    const map = new Map<string, LogEvent[]>();
    for (const e of events) map.set(e.template_id, [...(map.get(e.template_id) ?? []), e]);
    return map;
  }, [events]);
  const linesFor = useCallback(
    (id: string): LogEvent[] => {
      const e = byId.get(id);
      if (!e) return [];
      const data = (e.data ?? {}) as Record<string, unknown>;
      if (typeof data.line === "number") {
        const line = data.line;
        return events.filter((ev) => ev.line_no === line);
      }
      if (typeof data.template_id === "string") return byTemplate.get(data.template_id) ?? [];
      return [];
    },
    [byId, byTemplate, events],
  );
  const value = useMemo<EvidenceState>(
    () => ({
      byId,
      events,
      active: hovered ?? pinned,
      pinned,
      origin,
      originBelow,
      panelId,
      besidePanel,
      hover: setHovered,
      pin,
      linesFor,
    }),
    [byId, events, hovered, pinned, origin, originBelow, panelId, besidePanel, pin, linesFor],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useEvidence(): EvidenceState {
  const value = useContext(Ctx);
  if (!value) throw new Error("useEvidence needs an EvidenceProvider");
  return value;
}

function EvidencePreview({ evidence, lines }: { evidence: Evidence; lines: LogEvent[] }) {
  return (
    <div className="grid gap-2">
      <p className="text-xs text-muted-foreground">
        <span className="font-mono text-foreground">{evidence.id}</span>{" "}
        {KIND_LABEL[evidence.kind] ?? evidence.kind}, from {sourceLabel(evidence.source)}
      </p>
      <p className="text-sm leading-snug font-medium wrap-anywhere">{evidenceTitle(evidence)}</p>
      {evidenceDetail(evidence) ? (
        <p className="line-clamp-4 text-xs leading-5 wrap-anywhere whitespace-pre-wrap text-muted-foreground">
          {evidenceDetail(evidence)}
        </p>
      ) : null}
      <LogLines lines={lines} limit={4} />
      <p className="text-xs text-faint">Click the citation to keep it in the evidence panel.</p>
    </div>
  );
}

/**
 * Bring the evidence panel into view after a pin. In one column the panel sits above the report,
 * so the page scrolls up to it. Beside the report, the side column scrolls just far enough to
 * show the panel, and so does the page when the panel starts below the fold, as it does on a long
 * page's first screen (P3).
 */
function revealPanel(panelId: string, pinning = false) {
  const panel = document.getElementById(panelId);
  if (!panel) return;
  const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ? "auto"
    : "smooth";
  // Beside the report from 1280 px (the page's xl column); above it otherwise. Asked of the
  // screen, not of the markup: the panel's column is no longer an <aside> (RQ-M2).
  if (!window.matchMedia("(min-width: 1280px)").matches) {
    // Its top, where its title and "Back to the claim" are: "nearest" would show only the bottom
    // of a panel taller than the screen (J-M3).
    panel.scrollIntoView({ block: pinning ? "start" : "nearest", behavior });
    // Far from the claim, the reader continues from the panel: its "Back to the claim" is next.
    if (pinning && panel.getAttribute("tabindex") === "-1") panel.focus({ preventScroll: true });
    return;
  }
  // Beside the report, focus stays on the citation. "Nearest" moves the page no further than the
  // panel needs, and the column sticks before the claim beside it could leave the screen. A reader
  // already past the column (in Technical details) stays where they are.
  const column = scrollingParent(panel) ?? panel;
  if (pinning && column.getBoundingClientRect().bottom > 0) {
    panel.scrollIntoView({ block: "nearest", behavior });
  }
}

/** Whether the panel's top, where the evidence is named, shows inside the window and the column
 * that scrolls it, with room for a few lines under it. */
function panelInView(panelId: string): boolean {
  const panel = document.getElementById(panelId);
  if (!panel) return false;
  const { top, height } = panel.getBoundingClientRect();
  const column = scrollingParent(panel)?.getBoundingClientRect();
  const from = Math.max(0, column?.top ?? 0);
  const to = Math.min(window.innerHeight, column?.bottom ?? Infinity);
  return top >= from - 1 && top + Math.min(height, 160) <= to + 1;
}

/** The nearest ancestor that scrolls on its own, if any. */
function scrollingParent(element: HTMLElement): HTMLElement | null {
  for (let node = element.parentElement; node; node = node.parentElement) {
    const { overflowY } = window.getComputedStyle(node);
    if (overflowY === "auto" || overflowY === "scroll") return node;
  }
  return null;
}

// The citation "Back to the claim" hands focus back to; its preview card stays shut for that focus.
let returning: HTMLElement | null = null;

const HOVER = "(hover: hover) and (pointer: fine)";

function onHoverChange(changed: () => void) {
  const query = window.matchMedia(HOVER);
  query.addEventListener("change", changed);
  return () => query.removeEventListener("change", changed);
}

/** Whether the pointer can hover. On a touch screen a tap pins the evidence in the panel, and
 * no preview card opens over the report. */
function useCanHover(): boolean {
  return useSyncExternalStore(
    onHoverChange,
    () => window.matchMedia(HOVER).matches,
    () => true,
  );
}

/** Whether ``query`` matches; false when there is none. */
function useMatches(query: string | null): boolean {
  const subscribe = useCallback(
    (changed: () => void) => {
      if (!query) return () => {};
      const media = window.matchMedia(query);
      media.addEventListener("change", changed);
      return () => media.removeEventListener("change", changed);
    },
    [query],
  );
  return useSyncExternalStore(
    subscribe,
    () => (query ? window.matchMedia(query).matches : false),
    () => false,
  );
}

/**
 * A citation. Hovering or focusing it fills the evidence panel and, unless the panel is beside it
 * and in view, opens a card with the evidence by the citation; a click pins it in the panel (only
 * a pin is announced to screen readers).
 */
export function EvidenceChip({ id, label }: { id: string; label?: string }) {
  const { byId, active, pinned, panelId, besidePanel, hover, pin, linesFor } = useEvidence();
  const [preview, setPreview] = useState(false);
  const beside = useMatches(besidePanel);
  // After a click pins the evidence, the card stays shut until the pointer or focus leaves.
  const quiet = useRef(false);
  const canHover = useCanHover();
  const evidence = byId.get(id);
  const button = (
    <button
      type="button"
      disabled={!evidence}
      aria-pressed={pinned === id}
      aria-label={
        evidence
          ? `${label ? `Source ${label}` : `Evidence ${id}`}: ${KIND_LABEL[evidence.kind] ?? evidence.kind}, ${evidenceTitle(evidence)}`
          : `Evidence ${id} (missing)`
      }
      aria-controls={panelId}
      onMouseEnter={() => hover(id)}
      onMouseLeave={(event) => {
        hover(null);
        // A clicked citation keeps focus, and its card stays shut while it does, even when the
        // page scrolls to the evidence under a still pointer.
        if (document.activeElement !== event.currentTarget) quiet.current = false;
      }}
      onFocus={(event) => {
        hover(id);
        if (event.currentTarget === returning) {
          quiet.current = true;
          returning = null;
        }
      }}
      onBlur={() => {
        hover(null);
        quiet.current = false;
      }}
      onClick={(event) => {
        const pinning = pinned !== id;
        pin(pinning ? id : null, event.currentTarget);
        quiet.current = true; // the panel shows it now; a card on top would repeat it
        setPreview(false);
        requestAnimationFrame(() => revealPanel(panelId, pinning));
      }}
      className={cn(
        "inline-flex h-6 items-center rounded-xs border px-1.5 align-baseline font-mono text-xs transition-colors duration-(--duration-quick)",
        !evidence && "border-danger/60 text-danger line-through",
        evidence &&
          (active === id
            ? "border-primary bg-highlight text-highlight-foreground"
            : "border-control text-muted-foreground hover:border-foreground hover:text-foreground"),
      )}
    >
      {label ?? id}
    </button>
  );
  if (!evidence || !canHover) return button;
  return (
    <HoverCard
      open={preview}
      // Beside the report the panel shows the evidence, so no card repeats it there; but on a long
      // page's first screen the panel starts below the fold, and the card shows it instead (P3).
      onOpenChange={(open) =>
        setPreview(open && !quiet.current && !(beside && panelInView(panelId)))
      }
      openDelay={180}
      closeDelay={80}
    >
      <HoverCardTrigger asChild>{button}</HoverCardTrigger>
      <HoverCardContent
        side="top"
        className="max-h-(--radix-hover-card-content-available-height) w-96 max-w-[calc(100vw-2rem)] overflow-auto"
      >
        <EvidencePreview evidence={evidence} lines={linesFor(id)} />
      </HoverCardContent>
    </HoverCard>
  );
}

/**
 * What a log pattern can cite: its own evidence. ARIA keeps evidence for the patterns that stand
 * out, and the rest point at the whole window's counts, which say nothing about the pattern, so
 * those cite nothing (M3). An id that is not among the evidence stays, to show as missing.
 */
export function patternEvidence(
  template: Pick<TemplateStat, "template_id" | "evidence_id">,
  byId: ReadonlyMap<string, Evidence>,
): string[] {
  const evidence = byId.get(template.evidence_id);
  const about = (evidence?.data as Record<string, unknown> | null | undefined)?.template_id;
  return !evidence || (evidence.kind === "template" && about === template.template_id)
    ? [template.evidence_id]
    : [];
}

/** How many citations a claim shows before "+N": two read as sources, more as noise. */
const SHOWN_CITATIONS = 2;

export function Citations({
  ids,
  labels,
  className,
}: {
  ids: string[];
  /** Short names to show instead of the ids, such as an answer's source numbers. */
  labels?: ReadonlyMap<string, string>;
  className?: string;
}) {
  const [all, setAll] = useState(false);
  const list = useRef<HTMLSpanElement>(null);
  if (ids.length === 0) return null;
  const hidden = all ? 0 : Math.max(0, ids.length - SHOWN_CITATIONS);
  // The "+N" button goes once pressed: focus moves to the first source it showed, not the page
  // (FL-11).
  const showAll = () => {
    setAll(true);
    requestAnimationFrame(() =>
      list.current?.querySelectorAll<HTMLElement>("button")[SHOWN_CITATIONS]?.focus(),
    );
  };
  return (
    <span ref={list} className={cn("inline-flex flex-wrap gap-1 align-baseline", className)}>
      {ids.slice(0, ids.length - hidden).map((id) => (
        <EvidenceChip key={id} id={id} label={labels?.get(id)} />
      ))}
      {hidden ? (
        <button
          type="button"
          onClick={showAll}
          aria-label={`Show ${hidden} more ${hidden === 1 ? "source" : "sources"}`}
          className="inline-flex h-6 items-center rounded-xs border border-dashed border-control px-1.5 align-baseline font-mono text-xs text-muted-foreground hover:border-foreground hover:text-foreground"
        >
          +{hidden}
        </button>
      ) : null}
    </span>
  );
}

/** A value as text: "INFO 55, WARN 25" rather than {"INFO":55,"WARN":25}. */
function show(value: unknown): string {
  const flat = (v: unknown) => v === null || typeof v !== "object";
  const num = (v: unknown) =>
    typeof v === "boolean"
      ? v
        ? "yes"
        : "no"
      : typeof v === "number" && !Number.isInteger(v)
        ? String(+v.toFixed(3))
        : String(v);
  if (Array.isArray(value)) {
    return value.every(flat) ? value.map(num).join(", ") : JSON.stringify(value);
  }
  if (value && typeof value === "object") {
    const entries = Object.entries(value);
    return entries.every(([, v]) => flat(v))
      ? entries.map(([k, v]) => `${k} ${num(v)}`).join(", ")
      : JSON.stringify(value);
  }
  return num(value);
}

// Field names a reader would not guess; the rest read fine with spaces for underscores.
const FIELD_NAMES: Record<string, string> = {
  novel: "new to this system",
  synthetic: "built from a sample",
  error_like: "looks like an error",
  template_id: "pattern",
  duration_s: "duration, seconds",
  prediction_set: "short list",
  set_empty: "short list empty",
  coverage_target: "short list target",
  conformal: "calibrated short list",
  failure_mode: "kind of failure",
};

// A past incident's search scores, named for what each one measures.
const INCIDENT_FIELDS: Record<string, string> = {
  incident_id: "record",
  score: "match score",
  lexical: "shared words",
  dense: "similar meaning",
  rerank: "reranked match",
  occurrences: "times seen",
};

// The severity model's and the rules' numbers, named for what each one measures.
const MODEL_FIELDS: Record<string, string> = {
  probabilities: "how likely",
  sla_breach_risk: "risk of missing the deadline",
  top_contributions: "weighed most",
  outside_training: "unlike what it learned from",
  rule_id: "rule",
  effect: "what it does",
};

// Record ids, raw search scores and the model's settings: the title and detail already say what
// they mean (J-M4, RQ-m5).
const HIDDEN_FIELDS = new Set([
  "template_id",
  "incident_id",
  "score",
  "lexical",
  "dense",
  "rerank",
  "alpha",
  "conformal",
  "conformal_q",
  "set_empty",
  "temperature",
  "weight",
  "rules_version",
]);

/** A field's value as a person reads it: chances as percentages, the model's measurements by
 * name, the rest as recorded. `toward` is the level the measurements are weighed for. */
function fieldValue(key: string, value: unknown, toward: string | null): string {
  if (key === "failure_mode" && typeof value === "string") return failureName(value);
  if ((key === "coverage_target" || key === "sla_breach_risk") && typeof value === "number") {
    return chance(value);
  }
  if (key === "probabilities" && value && typeof value === "object" && !Array.isArray(value)) {
    return Object.entries(value)
      .map(([level, p]) => `${level} ${typeof p === "number" ? chance(p) : show(p)}`)
      .join(", ");
  }
  if (key === "effect" && (value === "score" || value === "floor")) {
    return value === "floor" ? "sets a safety floor" : "adds to a level's score";
  }
  if (key === "outside_training" && Array.isArray(value)) {
    return value.map((name) => featureName(String(name))).join(", ");
  }
  if (key === "top_contributions" && Array.isArray(value)) {
    return value
      .filter((part): part is [string, number] => Array.isArray(part) && part.length === 2)
      .map(([name, weight]) => {
        const side = weight >= 0 ? "for" : "against";
        return `${featureName(name)} (${side}${toward ? ` ${toward}` : ""})`;
      })
      .join(", ");
  }
  return show(value);
}

/** The most likely level in a model's probabilities, which its contributions are weighed for. */
function likeliest(data: Record<string, unknown>): string | null {
  const probabilities = data.probabilities;
  if (!probabilities || typeof probabilities !== "object" || Array.isArray(probabilities)) {
    return null;
  }
  let best: [string, number] | null = null;
  for (const [level, p] of Object.entries(probabilities)) {
    if (typeof p === "number" && (!best || p > best[1])) best = [level, p];
  }
  return best?.[0] ?? null;
}

// What each kind's title and detail already say: a tool's name and arguments, a cause's status and
// certainty, a runbook's file name.
const KIND_HIDDEN: Record<string, Set<string>> = {
  tool: new Set(["tool", "arguments", "agent"]),
  hypothesis: new Set(["id", "status", "confidence", "failure_mode", "component"]),
  runbook: new Set(["slug", "failure_modes"]),
};

// A tested cause's evidence, said as evidence rather than as field names.
const CAUSE_FIELDS: Record<string, string> = {
  supporting: "backed by",
  refuting: "against it",
};

function DataTable({ data, kind }: { data: Record<string, unknown>; kind: string }) {
  const entries = Object.entries(data).filter(
    ([k, v]) =>
      !HIDDEN_FIELDS.has(k) &&
      !KIND_HIDDEN[kind]?.has(k) &&
      !(k === "nodes" && v === 0) &&
      v !== null &&
      v !== "" &&
      !(Array.isArray(v) && v.length === 0),
  );
  if (entries.length === 0) return null;
  const names =
    kind === "incident"
      ? { ...FIELD_NAMES, ...INCIDENT_FIELDS }
      : kind === "model" || kind === "rule"
        ? { ...FIELD_NAMES, ...MODEL_FIELDS }
        : kind === "hypothesis"
          ? { ...FIELD_NAMES, ...CAUSE_FIELDS }
          : FIELD_NAMES;
  const toward = kind === "model" ? likeliest(data) : null;
  return (
    <dl className="grid grid-cols-[minmax(0,9rem)_1fr] gap-x-3 gap-y-1 text-xs">
      {entries.slice(0, 14).map(([key, value]) => (
        <div key={key} className="contents">
          <dt className="truncate text-muted-foreground">
            {names[key] ?? key.replace(/^n_/, "").replaceAll("_", " ")}
          </dt>
          <dd className="min-w-0 font-mono break-words">{fieldValue(key, value, toward)}</dd>
        </div>
      ))}
    </dl>
  );
}

// A log line or pattern can run to thousands of characters: past this, show its start and let the
// reader ask for the rest, so one line does not become a wall.
const LONG_LINE = 400;

/** A long line's start, and the whole of it on request. */
export function LongLine({ text }: { text: string }) {
  const [whole, setWhole] = useState(false);
  if (text.length <= LONG_LINE || whole) return <>{text}</>;
  return (
    <>
      {text.slice(0, LONG_LINE)}…{" "}
      <button
        type="button"
        onClick={() => setWhole(true)}
        className="font-sans text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
      >
        Show all {text.length.toLocaleString("en")} characters
      </button>
    </>
  );
}

export function LogLines({
  lines,
  limit = 12,
  sweep = false,
  more = true,
  label = "Log lines",
}: {
  lines: LogEvent[];
  limit?: number;
  /** The block's name, told apart from the page's other blocks of lines. */
  label?: string;
  /** Say how many lines are past the limit (off for a single example line). */
  more?: boolean;
  /** Sweep one pass of the highlight across the lines as they appear (globals.css: .thread-pass). */
  sweep?: boolean;
}) {
  if (lines.length === 0) return null;
  const list = (
    <ol>
      {lines.slice(0, limit).map((line, i) => (
        <li
          key={line.idx}
          className={cn(
            // Long lines wrap under their own message, so nothing hides past the panel's edge.
            "grid grid-cols-[2.5rem_2.75rem_1fr] gap-2 px-2 wrap-anywhere whitespace-pre-wrap",
            sweep && "thread-pass",
          )}
          style={sweep ? ({ "--thread-i": i } as CSSProperties) : undefined}
        >
          <span className="tabular text-right text-faint">{line.line_no ?? line.idx + 1}</span>
          <span
            className={
              line.level === "WARN"
                ? "text-sev2-fg"
                : line.level && /ERR|FATAL|CRIT|SEVERE/.test(line.level)
                  ? "text-sev1-fg"
                  : "text-faint"
            }
          >
            {line.level ?? ""}
          </span>
          <span>
            <LongLine text={line.message} />
          </span>
        </li>
      ))}
    </ol>
  );
  return (
    <div className="grid gap-1">
      <div
        role="group"
        aria-label={label}
        className="min-w-0 rounded-sm border border-rule bg-sunken py-1.5 font-mono text-xs leading-5"
      >
        {list}
      </div>
      {more && lines.length > limit ? (
        <p className="text-xs text-muted-foreground">
          and {(lines.length - limit).toLocaleString("en")} more lines like these
        </p>
      ) : null}
    </div>
  );
}

/** A tool's result as it came back, folded away: the detail above says what it means. */
export function RawResult({ evidence }: { evidence: Evidence }) {
  const raw = rawResult(evidence);
  if (!raw) return null;
  return (
    <details className="text-xs">
      <summary className="w-fit cursor-pointer text-muted-foreground underline decoration-control underline-offset-4 hover:text-foreground">
        Show the raw result
      </summary>
      <pre
        tabIndex={0}
        role="region"
        aria-label="Raw result"
        className="mt-2 max-h-48 overflow-auto rounded-sm bg-sunken p-2 leading-5 whitespace-pre-wrap"
      >
        {raw}
      </pre>
    </details>
  );
}

/** The way to a runbook's own page, from the evidence that cites it. */
function RunbookLink({ evidence }: { evidence: Evidence }) {
  const slug = (evidence.data as Record<string, unknown> | null | undefined)?.slug;
  if (evidence.kind !== "runbook" || typeof slug !== "string") return null;
  return (
    <Link
      href={`/console/runbooks/${encodeURIComponent(slug)}` as never}
      className="inline-flex w-fit items-center gap-1 text-xs underline decoration-control underline-offset-4 hover:decoration-foreground"
    >
      Open the runbook
      <ArrowRightIcon aria-hidden className="size-3.5" />
    </Link>
  );
}

/** The evidence behind whatever citation the reader is pointing at. */
export function EvidencePanel({ className }: { className?: string }) {
  const { active, pinned, origin, originBelow, panelId, byId, pin, linesFor } = useEvidence();
  const evidence = active ? byId.get(active) : undefined;
  // In one column the panel sits above later citations, so it opens only on a click there:
  // appearing on hover or focus would push the citation being read down the page.
  // In one column the page scrolled to this panel; this takes the reader back to the claim.
  const BackIcon = originBelow ? ArrowDownIcon : ArrowUpIcon;
  const backToClaim = () => {
    if (!origin?.isConnected) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    origin.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
    returning = origin;
    origin.focus({ preventScroll: true });
  };
  const pinnedEvidence = pinned ? byId.get(pinned) : undefined;
  return (
    <section
      id={panelId}
      aria-label="Evidence"
      // Focus lands here after a pin in one column, where the panel sits far below the claim.
      tabIndex={-1}
      className={cn(
        "grid min-w-0 content-start gap-3 rounded-lg bg-raised p-4 outline-none focus-visible:ring-2 focus-visible:ring-ring sm:p-5",
        !(evidence && pinned) && "max-xl:hidden",
        className,
      )}
    >
      {/* Only a pin is announced, in a few words: a citation's own name already gives its title,
          and reading whole cards out as focus moves would bury the report. */}
      <p className="sr-only" aria-live="polite">
        {pinnedEvidence ? `Pinned ${pinnedEvidence.id}: ${evidenceTitle(pinnedEvidence)}` : ""}
      </p>
      {evidence ? (
        <>
          <div className="flex items-start justify-between gap-3">
            <div className="grid min-w-0 gap-1">
              <p className="text-xs text-muted-foreground">
                <span className="font-mono text-foreground">{evidence.id}</span>{" "}
                {KIND_LABEL[evidence.kind] ?? evidence.kind}, from {sourceLabel(evidence.source)}
              </p>
              <h3 className="font-sans text-sm leading-snug font-semibold wrap-anywhere">
                {evidenceTitle(evidence)}
              </h3>
            </div>
            {pinned === evidence.id ? (
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label="Unpin evidence"
                onClick={() => pin(null)}
              >
                <XIcon aria-hidden />
              </Button>
            ) : (
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label="Pin this evidence"
                onClick={() => pin(evidence.id)}
              >
                <PinIcon aria-hidden />
              </Button>
            )}
          </div>
          {pinned === evidence.id && origin ? (
            <Button
              size="sm"
              variant="ghost"
              className="-my-1 -ml-2 justify-self-start xl:hidden"
              onClick={backToClaim}
            >
              <BackIcon aria-hidden />
              Back to the claim
            </Button>
          ) : null}
          {evidenceDetail(evidence) ? (
            <pre
              tabIndex={0}
              role="region"
              aria-label="Evidence detail"
              className="max-h-48 overflow-auto rounded-sm bg-sunken p-2 text-xs leading-5 whitespace-pre-wrap"
            >
              {evidenceDetail(evidence)}
            </pre>
          ) : null}
          <RawResult evidence={evidence} />
          <RunbookLink evidence={evidence} />
          {/* Keyed by evidence, so each citation pointed at sends its own pass of light. */}
          <LogLines
            key={evidence.id}
            lines={linesFor(evidence.id)}
            sweep
            label={`Log lines behind ${evidence.id}`}
          />
          <DataTable data={(evidence.data ?? {}) as Record<string, unknown>} kind={evidence.kind} />
        </>
      ) : (
        <div className="grid gap-1.5">
          <h3 className="font-sans text-sm font-semibold">Evidence</h3>
          <p className="text-sm text-muted-foreground">
            Every claim in the report cites evidence like{" "}
            <span className="rounded-xs border border-control px-1 font-mono text-xs">E3</span>.
            Point at one, or focus it with the keyboard, to see what it rests on; click to keep it
            here.
          </p>
        </div>
      )}
    </section>
  );
}
