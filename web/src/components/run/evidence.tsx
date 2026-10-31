"use client";

import { ArrowUpIcon, PinIcon, XIcon } from "lucide-react";
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
import type { Evidence, LogEvent } from "@/lib/api/types";
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
};

/** Where evidence came from, in words: "the severity rules" rather than "severity.rules". */
export const sourceLabel = (source: string) => SOURCE_LABEL[source] ?? source;

export const KIND_LABEL: Record<string, string> = {
  log: "Log line",
  template: "Log template",
  feature: "Computed feature",
  rule: "Severity rule",
  model: "Model output",
  alert: "Alert",
  incident: "Past incident",
  tickets: "Ticket history",
  runbook: "Runbook",
  tool: "Tool call",
  hypothesis: "Hypothesis",
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
  /** The element that shows a pinned citation: the evidence panel, or an answer's sources. */
  panelId: string;
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
  children,
}: {
  evidence: Evidence[];
  events: LogEvent[];
  panelId?: string;
  children: ReactNode;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const [origin, setOrigin] = useState<HTMLElement | null>(null);
  const pin = useCallback((id: string | null, from: HTMLElement | null = null) => {
    setPinned(id);
    setOrigin(id ? from : null);
  }, []);
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
      panelId,
      hover: setHovered,
      pin,
      linesFor,
    }),
    [byId, events, hovered, pinned, origin, panelId, pin, linesFor],
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
      <p className="text-sm leading-snug font-medium wrap-anywhere">{evidence.title}</p>
      {evidence.detail ? (
        <p className="line-clamp-4 text-xs leading-5 wrap-anywhere whitespace-pre-wrap text-muted-foreground">
          {evidence.detail}
        </p>
      ) : null}
      <LogLines lines={lines} limit={4} wrap />
      <p className="text-xs text-faint">Click the citation to keep it in the evidence panel.</p>
    </div>
  );
}

/**
 * Bring the evidence panel into view after a pin. Beside the report the side column scrolls on
 * its own, just far enough to show the panel, so the page stays put; in one column the panel sits
 * below the report, so the page scrolls to it.
 */
function revealPanel(panelId: string) {
  const panel = document.getElementById(panelId);
  if (!panel) return;
  const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ? "auto"
    : "smooth";
  const column = panel.closest("aside");
  if (!column || !window.matchMedia("(min-width: 1280px)").matches) {
    panel.scrollIntoView({ block: "nearest", behavior });
    return;
  }
  const top = panel.offsetTop;
  const bottom = top + panel.offsetHeight;
  const { scrollTop, clientHeight } = column;
  if (top < scrollTop) column.scrollTo({ top, behavior });
  else if (bottom > scrollTop + clientHeight) {
    column.scrollTo({ top: Math.min(top, bottom - clientHeight), behavior });
  }
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

/**
 * A citation. Hovering shows the evidence beside it; focusing or hovering also fills the
 * evidence panel (announced to screen readers); a click pins it there.
 */
export function EvidenceChip({ id, label }: { id: string; label?: string }) {
  const { byId, active, pinned, panelId, hover, pin, linesFor } = useEvidence();
  const [preview, setPreview] = useState(false);
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
          ? `${label ? `Source ${label}` : `Evidence ${id}`}: ${KIND_LABEL[evidence.kind] ?? evidence.kind}, ${evidence.title}`
          : `Evidence ${id} (missing)`
      }
      aria-controls={panelId}
      onMouseEnter={() => hover(id)}
      onMouseLeave={() => {
        hover(null);
        quiet.current = false;
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
        pin(pinned === id ? null : id, event.currentTarget);
        quiet.current = true; // the panel shows it now; a card on top would repeat it
        setPreview(false);
        requestAnimationFrame(() => revealPanel(panelId));
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
      onOpenChange={(open) => setPreview(open && !quiet.current)}
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
  if (ids.length === 0) return null;
  const hidden = all ? 0 : Math.max(0, ids.length - SHOWN_CITATIONS);
  return (
    <span className={cn("inline-flex flex-wrap gap-1 align-baseline", className)}>
      {ids.slice(0, ids.length - hidden).map((id) => (
        <EvidenceChip key={id} id={id} label={labels?.get(id)} />
      ))}
      {hidden ? (
        <button
          type="button"
          onClick={() => setAll(true)}
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
};

function DataTable({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data).filter(
    ([, v]) => v !== null && v !== "" && !(Array.isArray(v) && v.length === 0),
  );
  if (entries.length === 0) return null;
  return (
    <dl className="grid grid-cols-[minmax(0,9rem)_1fr] gap-x-3 gap-y-1 text-xs">
      {entries.slice(0, 14).map(([key, value]) => (
        <div key={key} className="contents">
          <dt className="truncate text-muted-foreground">
            {FIELD_NAMES[key] ?? key.replace(/^n_/, "").replaceAll("_", " ")}
          </dt>
          <dd className="min-w-0 font-mono break-words">{show(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

export function LogLines({
  lines,
  limit = 12,
  wrap = false,
  sweep = false,
  more = true,
  label = "Log lines",
}: {
  lines: LogEvent[];
  limit?: number;
  /** The scrolling block's name, told apart from the page's other blocks of lines. */
  label?: string;
  /** Say how many lines are past the limit (off for a single example line). */
  more?: boolean;
  /** Wrap long lines instead of scrolling (inside hover cards, where nothing can take focus). */
  wrap?: boolean;
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
            "grid grid-cols-[2.5rem_2.75rem_1fr] gap-2 px-2",
            wrap ? "break-all whitespace-pre-wrap" : "whitespace-pre",
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
          <span>{line.message}</span>
        </li>
      ))}
    </ol>
  );
  const frame = "rounded-sm border border-rule bg-sunken py-1.5 font-mono text-xs leading-5";
  return (
    <div className="grid gap-1">
      {wrap ? (
        <div className={frame}>{list}</div>
      ) : (
        <div tabIndex={0} role="region" aria-label={label} className={cn(frame, "overflow-x-auto")}>
          {list}
        </div>
      )}
      {more && lines.length > limit ? (
        <p className="text-xs text-muted-foreground">
          and {(lines.length - limit).toLocaleString("en")} more lines like these
        </p>
      ) : null}
    </div>
  );
}

/** The evidence behind whatever citation the reader is pointing at. */
export function EvidencePanel({ className }: { className?: string }) {
  const { active, pinned, origin, panelId, byId, pin, linesFor } = useEvidence();
  const evidence = active ? byId.get(active) : undefined;
  // In one column the panel sits above later citations, so it opens only on a click there:
  // appearing on hover or focus would push the citation being read down the page.
  // In one column the page scrolled down to this panel; this takes the reader back up.
  const backToClaim = () => {
    if (!origin?.isConnected) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    origin.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
    returning = origin;
    origin.focus({ preventScroll: true });
  };
  return (
    <section
      id={panelId}
      aria-label="Evidence"
      aria-live="polite"
      className={cn(
        "grid min-w-0 content-start gap-3 rounded-lg bg-raised p-4 sm:p-5",
        !(evidence && pinned) && "max-xl:hidden",
        className,
      )}
    >
      {evidence ? (
        <>
          <div className="flex items-start justify-between gap-3">
            <div className="grid min-w-0 gap-1">
              <p className="text-xs text-muted-foreground">
                <span className="font-mono text-foreground">{evidence.id}</span>{" "}
                {KIND_LABEL[evidence.kind] ?? evidence.kind}, from {sourceLabel(evidence.source)}
              </p>
              <h3 className="font-sans text-sm leading-snug font-semibold wrap-anywhere">
                {evidence.title}
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
              <ArrowUpIcon aria-hidden />
              Back to the claim
            </Button>
          ) : null}
          {evidence.detail ? (
            <pre
              tabIndex={0}
              role="region"
              aria-label="Evidence detail"
              className="max-h-48 overflow-auto rounded-sm bg-sunken p-2 text-xs leading-5 whitespace-pre-wrap"
            >
              {evidence.detail}
            </pre>
          ) : null}
          {/* Keyed by evidence, so each citation pointed at sends its own pass of light. */}
          <LogLines
            key={evidence.id}
            lines={linesFor(evidence.id)}
            sweep
            label={`Log lines behind ${evidence.id}`}
          />
          <DataTable data={(evidence.data ?? {}) as Record<string, unknown>} />
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
